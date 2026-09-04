"""Подключение к общему OpenCode Server и lifecycle создаваемого процесса."""
from __future__ import annotations

import atexit
import json
import logging
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from config.mcp_profiles import AUTODEPLOY_MCP_NAME

from opencode_integration.client import (
    OpenCodeAgentMissingError,
    OpenCodeClient,
    OpenCodeError,
)

OPENCODE_HOST = "127.0.0.1"
DEFAULT_SERVER_URL = "http://127.0.0.1:4096"
FORM_EXTRACTOR_AGENT = "form-extractor"
FORM_ROUTER_AGENT = "form-router"
AUTODEPLOY_COPILOT_AGENT = "autodeploy-copilot"
FORM_SEARCH_AGENT = "form-search"
REPOSITORY_RESEARCHER_AGENT = "repository-researcher"
REQUIRED_AGENTS = (
    FORM_EXTRACTOR_AGENT,
    FORM_ROUTER_AGENT,
    AUTODEPLOY_COPILOT_AGENT,
    FORM_SEARCH_AGENT,
    REPOSITORY_RESEARCHER_AGENT,
)
TARGET_OPENCODE_VERSION = "1.18.18"
_log = logging.getLogger("opencode.manager")


class OpenCodeManagerError(OpenCodeError):
    """К серверу нельзя подключиться или его нельзя запустить безопасно."""


@dataclass(frozen=True)
class ManagerStatus:
    state: str
    message: str
    version: str = ""
    address: str = ""
    pid: Optional[int] = None
    agent_loaded: bool = False
    ownership: str = "none"  # none | external | owned
    runtime_dir: str = ""


def default_runtime_dir() -> Path:
    """Отдельный ASCII-friendly каталог, куда OpenCode может ставить plugin deps."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "gravitee-autodeploy-ui" / "opencode-runtime"


class OpenCodeManager:
    """Один активный client: внешний сервер либо созданный формой процесс."""

    def __init__(
        self,
        project_dir: Path,
        *,
        command: str = "opencode",
        server_url: str = DEFAULT_SERVER_URL,
        connect_timeout: float = 10.0,
        startup_timeout: float = 20.0,
        request_timeout: float = 120.0,
        username: str = "opencode",
        password: str = "",
        runtime_dir: Path | None = None,
        agent_source_dir: Path | None = None,
        mcp_url: str = "",
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        source_dir = Path(
            agent_source_dir or self.project_dir / ".opencode" / "agents"
        ).resolve()
        self.agent_source = (
            source_dir / "form-extractor.md"
        )
        self.agent_sources = tuple(
            source_dir / f"{name}.md"
            for name in REQUIRED_AGENTS
        )
        self.runtime_dir = Path(runtime_dir or default_runtime_dir()).resolve()
        self.command = command
        self.server_url = server_url.strip() or DEFAULT_SERVER_URL
        self.connect_timeout = self._timeout_value(connect_timeout)
        self.startup_timeout = self._timeout_value(startup_timeout)
        self.request_timeout = self._timeout_value(request_timeout)
        self.username = username.strip() or "opencode"
        self.password = password
        self.mcp_url = mcp_url.strip()

        self._lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._cancel = threading.Event()
        self._process: Optional[subprocess.Popen[str]] = None
        self._client: Optional[OpenCodeClient] = None
        self._status = ManagerStatus(
            "stopped",
            "OpenCode Server не подключён",
            address=self.server_url,
            runtime_dir=str(self.runtime_dir),
        )
        self._ownership = "none"
        self._generation = 0
        self._stopping = False
        atexit.register(self.stop)

    def configure(
        self,
        *,
        server_url: Optional[str] = None,
        connect_timeout: Optional[float] = None,
        startup_timeout: Optional[float] = None,
        request_timeout: Optional[float] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        with self._lock:
            if server_url is not None:
                # Валидацию выполняет тот же клиент, что будет делать запросы.
                OpenCodeClient(
                    server_url,
                    timeout=self._timeout_value(
                        connect_timeout
                        if connect_timeout is not None
                        else self.connect_timeout
                    ),
                    directory=self.runtime_dir,
                )
                self.server_url = server_url.rstrip("/")
            if connect_timeout is not None:
                self.connect_timeout = self._timeout_value(connect_timeout)
            if startup_timeout is not None:
                self.startup_timeout = self._timeout_value(startup_timeout)
            if request_timeout is not None:
                self.request_timeout = self._timeout_value(request_timeout)
            if username is not None:
                self.username = username.strip() or "opencode"
            if password is not None:
                self.password = password
            if self._client is not None:
                self._client.timeout = self.request_timeout

    @property
    def client(self) -> Optional[OpenCodeClient]:
        with self._lock:
            if not self._ready_locked():
                return None
            return self._client

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return self._ready_locked()

    def _ready_locked(self) -> bool:
        if self._status.state != "ready" or self._client is None:
            return False
        if self._ownership == "owned":
            return self._process is not None and self._process.poll() is None
        return self._ownership == "external"

    @property
    def status(self) -> ManagerStatus:
        with self._lock:
            if (
                self._ownership == "owned"
                and self._process is not None
                and self._process.poll() is not None
                and self._status.state == "ready"
                and not self._stopping
            ):
                self._set_status_locked(
                    ManagerStatus(
                        "error",
                        f"Созданный OpenCode аварийно завершился с кодом "
                        f"{self._process.returncode}",
                        version=self._status.version,
                        address=self._status.address,
                        pid=self._process.pid,
                        ownership="owned",
                        runtime_dir=str(self.runtime_dir),
                    )
                )
                self._client = None
            return self._status

    def connect(
        self,
        address: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
    ) -> OpenCodeClient:
        """Подключается к уже работающему серверу; вызывать из worker thread."""
        target = (address or self.server_url).strip().rstrip("/")
        effective_timeout = self._timeout_value(
            timeout if timeout is not None else self.connect_timeout
        )
        with self._lifecycle_lock:
            self._cancel.clear()
            self._clear_connection(terminate_owned=True, set_stopped=False)
            self._set_status(
                "connecting",
                f"Попытка подключения к серверу {target}…",
                address=target,
                ownership="external",
            )
            deadline = time.monotonic() + effective_timeout
            try:
                self._prepare_runtime()
                client = self._make_client(target)
                health = client.health(timeout=self._remaining(deadline))
                if not health.healthy:
                    raise OpenCodeManagerError("health check вернул healthy=false")
                self._set_status(
                    "connecting",
                    "Сервер отвечает. Проверяю AI-агентов…",
                    version=health.version,
                    address=target,
                    ownership="external",
                )
                self._require_agents(client, deadline=deadline)
                if self._cancel.is_set():
                    raise OpenCodeManagerError("Подключение к OpenCode отменено")
            except Exception as exc:
                with self._lock:
                    self._client = None
                    self._ownership = "none"
                self._set_status(
                    "error",
                    f"Не удалось подключиться к серверу {target}: {exc}",
                    address=target,
                )
                raise OpenCodeManagerError(self._status.message) from exc

            with self._lock:
                self.server_url = target
                self._client = client
                self._ownership = "external"
            self._set_status(
                "ready",
                f"Успешно подключено к серверу {target}",
                version=health.version,
                address=target,
                agent_loaded=True,
                ownership="external",
            )
            return client

    def connect_async(
        self,
        address: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
        on_ready: Optional[Callable[[OpenCodeClient], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> threading.Thread:
        return self._run_async(
            "opencode-connect",
            lambda: self.connect(address, timeout=timeout),
            on_ready,
            on_error,
        )

    def create(self, *, port: int = 0) -> OpenCodeClient:
        """Создаёт дочерний localhost-only server в изолированной директории."""
        with self._lifecycle_lock:
            self._cancel.clear()
            self._clear_connection(terminate_owned=True, set_stopped=False)
            self._set_status(
                "starting",
                "Проверяю команду OpenCode перед созданием сервера…",
                ownership="owned",
            )
            executable = shutil.which(self.command)
            if executable is None:
                return self._create_failed(
                    "Команда 'opencode' не найдена в PATH. Установите OpenCode 1.18.18."
                )
            try:
                self._prepare_runtime()
                version = self._detect_version(executable)
            except Exception as exc:
                return self._create_failed(f"Не удалось подготовить OpenCode: {exc}", exc)

            last_error: Optional[Exception] = None
            for attempt in range(1, 4):
                if self._cancel.is_set():
                    last_error = OpenCodeManagerError("Создание сервера отменено")
                    break
                try:
                    selected_port = int(port) if port else self._pick_free_port()
                    address = f"http://{OPENCODE_HOST}:{selected_port}"
                    self._set_status(
                        "starting",
                        f"Попытка создать и подключить OpenCode Server {address} "
                        f"(попытка {attempt}/3)…",
                        version=version,
                        address=address,
                        ownership="owned",
                    )
                    process = self._spawn(executable, selected_port)
                    with self._lock:
                        self._process = process
                        self._ownership = "owned"
                        self._generation += 1
                        generation = self._generation
                    client = self._make_client(address)
                    self._wait_until_ready(client, process)
                    self._set_status(
                        "starting",
                        "Сервер создан. Проверяю AI-агентов…",
                        version=version,
                        address=address,
                        pid=process.pid,
                        ownership="owned",
                    )
                    self._require_agents(
                        client,
                        timeout=min(10.0, self.startup_timeout),
                    )
                    if self._cancel.is_set():
                        raise OpenCodeManagerError("Создание сервера отменено")
                    with self._lock:
                        self._client = client
                        self._ownership = "owned"
                        self.server_url = address
                    self._set_status(
                        "ready",
                        f"Сервер создан и подключён: {address}",
                        version=version,
                        address=address,
                        pid=process.pid,
                        agent_loaded=True,
                        ownership="owned",
                    )
                    self._start_exit_monitor(process, generation)
                    return client
                except Exception as exc:
                    last_error = exc
                    self._clear_connection(terminate_owned=True, set_stopped=False)
                    if port or isinstance(exc, OpenCodeAgentMissingError):
                        break
            detail = str(last_error) if last_error else "неизвестная ошибка"
            return self._create_failed(
                f"Не удалось создать OpenCode Server: {detail}",
                last_error,
                version=version,
            )

    # Совместимость со старым API и формами, которые вызывают manager.start().
    def start(self) -> OpenCodeClient:
        return self.create()

    def start_async(
        self,
        *,
        on_ready: Optional[Callable[[OpenCodeClient], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> threading.Thread:
        return self.create_async(on_ready=on_ready, on_error=on_error)

    def create_async(
        self,
        *,
        port: int = 0,
        on_ready: Optional[Callable[[OpenCodeClient], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> threading.Thread:
        return self._run_async(
            "opencode-create",
            lambda: self.create(port=port),
            on_ready,
            on_error,
        )

    @staticmethod
    def _run_async(
        name: str,
        operation: Callable[[], OpenCodeClient],
        on_ready: Optional[Callable[[OpenCodeClient], None]],
        on_error: Optional[Callable[[Exception], None]],
    ) -> threading.Thread:
        def worker() -> None:
            try:
                client = operation()
            except Exception as exc:
                if on_error is not None:
                    on_error(exc)
            else:
                if on_ready is not None:
                    on_ready(client)

        thread = threading.Thread(target=worker, name=name, daemon=True)
        thread.start()
        return thread

    def check_status(self) -> ManagerStatus:
        """Повторяет health/agent-check текущего адреса без создания процесса."""
        with self._lifecycle_lock:
            with self._lock:
                existing = self._client
                address = (
                    existing.base_url
                    if existing is not None
                    else self._status.address or self.server_url
                )
                ownership = (
                    self._ownership
                    if self._ownership in {"external", "owned"}
                    else "external"
                )
                process = self._process
            self._set_status(
                "checking",
                f"Проверяю состояние сервера {address}…",
                address=address,
                ownership=ownership,
                pid=process.pid if process else None,
            )
            try:
                self._prepare_runtime()
                client = existing or self._make_client(address)
                health = client.health(timeout=self.connect_timeout)
                if not health.healthy:
                    raise OpenCodeManagerError("health check вернул healthy=false")
                self._require_agents(
                    client,
                    timeout=min(self.connect_timeout, 10.0),
                )
            except Exception as exc:
                self._set_status(
                    "error",
                    f"Проверка сервера {address} не пройдена: {exc}",
                    address=address,
                    ownership=ownership,
                    pid=process.pid if process else None,
                )
                raise OpenCodeManagerError(self._status.message) from exc
            with self._lock:
                self._client = client
                self._ownership = ownership
            self._set_status(
                "ready",
                f"Сервер отвечает: {address}",
                version=health.version,
                address=address,
                agent_loaded=True,
                ownership=ownership,
                pid=process.pid if process else None,
            )
            return self.status

    def probe_health(self, *, timeout: float = 3.0) -> ManagerStatus:
        """Тихо перепроверяет активное соединение; предназначено для UI-monitor."""
        with self._lifecycle_lock:
            with self._lock:
                client = self._client
                previous = self._status
                ownership = self._ownership
                process = self._process
            if client is None or previous.state != "ready":
                return self.status
            try:
                effective_timeout = min(
                    self._timeout_value(timeout),
                    max(0.1, self.connect_timeout),
                )
                health = client.health(timeout=effective_timeout)
                if not health.healthy:
                    raise OpenCodeManagerError("health check вернул healthy=false")
                self._require_agents(client, timeout=effective_timeout)
            except Exception as exc:
                with self._lock:
                    # Сохраняем ownership: owned process всё равно должен быть
                    # корректно завершён при закрытии приложения.
                    self._client = None
                self._set_status(
                    "error",
                    f"Соединение с OpenCode Server {previous.address} потеряно: {exc}",
                    version=previous.version,
                    address=previous.address,
                    pid=process.pid if process else previous.pid,
                    ownership=ownership,
                )
                raise OpenCodeManagerError(self._status.message) from exc
            return self.status

    def restart(self) -> OpenCodeClient:
        with self._lock:
            if self._ownership != "owned":
                raise OpenCodeManagerError(
                    "Перезапуск доступен только для сервера, созданного формой"
                )
        self.stop()
        return self.create()

    def disconnect(self) -> None:
        """Отключает client, не завершая внешний server."""
        self._cancel.set()
        with self._lifecycle_lock:
            with self._lock:
                owned = self._ownership == "owned"
            self._clear_connection(terminate_owned=owned, set_stopped=True)

    def stop(self) -> None:
        """Завершает только owned process; внешний server никогда не трогает."""
        self._cancel.set()
        with self._lifecycle_lock:
            with self._lock:
                owned = self._ownership == "owned"
            self._clear_connection(terminate_owned=owned, set_stopped=True)

    def _prepare_runtime(self) -> None:
        missing = [source for source in self.agent_sources if not source.is_file()]
        if missing:
            raise OpenCodeManagerError(
                "Не найдены файлы AI-агентов: "
                + ", ".join(str(source) for source in missing)
            )
        # Не позволяем случайно вернуть OpenCode в каталог репозитория.
        try:
            self.runtime_dir.relative_to(self.project_dir)
        except ValueError:
            pass
        else:
            raise OpenCodeManagerError(
                "OpenCode runtime должен находиться вне каталога проекта"
            )
        agent_dir = self.runtime_dir / ".opencode" / "agents"
        agent_dir.mkdir(parents=True, exist_ok=True)
        try:
            agent_dir.resolve().relative_to(self.runtime_dir)
        except ValueError as exc:
            raise OpenCodeManagerError(
                "Каталог агентов OpenCode через symlink выходит за пределы runtime"
            ) from exc
        for source in self.agent_sources:
            destination = agent_dir / source.name
            if destination.is_symlink():
                raise OpenCodeManagerError(
                    "Файл runtime-агента не должен быть symbolic link"
                )
            source_text = source.read_text(encoding="utf-8")
            if (
                not destination.exists()
                or destination.read_text(encoding="utf-8") != source_text
            ):
                destination.write_text(source_text, encoding="utf-8")
        self._prepare_mcp_config()
        _log.info("runtime prepared directory=%s", self.runtime_dir)

    def _prepare_mcp_config(self) -> None:
        """Merge only our remote MCP entry into the isolated project config."""
        config_path = self.runtime_dir / "opencode.json"
        if config_path.is_symlink():
            raise OpenCodeManagerError("opencode.json runtime не должен быть symbolic link")
        config: dict[str, object] = {}
        if config_path.is_file():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OpenCodeManagerError(f"Некорректный runtime opencode.json: {exc}") from exc
            if not isinstance(loaded, dict):
                raise OpenCodeManagerError("runtime opencode.json должен быть JSON object")
            config = loaded
        mcp = config.get("mcp")
        if mcp is None:
            mcp_map: dict[str, object] = {}
            config["mcp"] = mcp_map
        elif isinstance(mcp, dict):
            mcp_map = mcp
        else:
            raise OpenCodeManagerError("opencode.json: mcp должен быть JSON object")
        if self.mcp_url:
            parsed = urlsplit(self.mcp_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
                raise OpenCodeManagerError("AutoDeploy MCP разрешён только по localhost HTTP")
            mcp_map[AUTODEPLOY_MCP_NAME] = {
                "type": "remote",
                "url": self.mcp_url,
                "enabled": True,
            }
        else:
            mcp_map.pop(AUTODEPLOY_MCP_NAME, None)
        config.setdefault("$schema", "https://opencode.ai/config.json")
        temporary = config_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(config_path)

    @staticmethod
    def _require_agents(
        client: OpenCodeClient,
        *,
        deadline: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> None:
        for agent_name in REQUIRED_AGENTS:
            effective_timeout = (
                OpenCodeManager._remaining(deadline)
                if deadline is not None
                else timeout
            )
            client.require_agent(agent_name, timeout=effective_timeout)

    def _make_client(self, address: str) -> OpenCodeClient:
        return OpenCodeClient(
            address,
            timeout=self.request_timeout,
            directory=self.runtime_dir,
            username=self.username,
            password=self.password,
        )

    def _detect_version(self, executable: str) -> str:
        try:
            completed = subprocess.run(
                [executable, "--version"],
                # Даже безобидная команда версии у некоторых сборок OpenCode
                # инициализирует project plugins. Никогда не даём ей cwd проекта.
                cwd=str(self.runtime_dir),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise OpenCodeManagerError(
                f"Не удалось выполнить opencode --version: {exc}"
            ) from exc
        combined = f"{completed.stdout}\n{completed.stderr}".strip()
        if completed.returncode != 0:
            raise OpenCodeManagerError(
                f"opencode --version завершился с кодом {completed.returncode}"
            )
        match = re.search(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", combined)
        if not match:
            raise OpenCodeManagerError("Не удалось определить версию OpenCode")
        version = match.group(0)
        if version != TARGET_OPENCODE_VERSION:
            _log.warning(
                "OpenCode version mismatch actual=%s target=%s",
                version,
                TARGET_OPENCODE_VERSION,
            )
        return version

    @staticmethod
    def _pick_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((OPENCODE_HOST, 0))
            return int(sock.getsockname()[1])

    def _spawn(self, executable: str, port: int) -> subprocess.Popen[str]:
        environment = os.environ.copy()
        if self.password:
            environment["OPENCODE_SERVER_PASSWORD"] = self.password
            environment["OPENCODE_SERVER_USERNAME"] = self.username
        else:
            # Не наследуем случайный password из shell: иначе созданный server
            # потребует auth, о котором клиент формы не знает.
            environment.pop("OPENCODE_SERVER_PASSWORD", None)
            environment.pop("OPENCODE_SERVER_USERNAME", None)
        kwargs: dict[str, object] = {
            "cwd": str(self.runtime_dir),
            "stdin": subprocess.DEVNULL,
            # Читаются отдельными daemon threads. Перед записью строки проходят
            # фильтр контента и redaction в core.logging_setup.
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": environment,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [
                executable,
                "serve",
                "--hostname",
                OPENCODE_HOST,
                "--port",
                str(port),
            ],
            **kwargs,  # type: ignore[arg-type]
        )
        self._start_stream_loggers(process)
        _log.info("server process started pid=%s host=%s port=%s", process.pid, OPENCODE_HOST, port)
        return process

    @staticmethod
    def _start_stream_loggers(process: subprocess.Popen[str]) -> None:
        """Дренирует stdout/stderr сервера, не допуская зависания PIPE."""
        from core.logging_setup import sanitize_server_log_line

        def reader(stream, level: int, channel: str) -> None:
            if stream is None:
                return
            try:
                for raw_line in iter(stream.readline, ""):
                    safe = sanitize_server_log_line(raw_line)
                    if safe:
                        _log.log(level, "server[%s] %s", channel, safe)
            except Exception:
                _log.warning(
                    "server log reader failed channel=%s pid=%s",
                    channel,
                    process.pid,
                    exc_info=True,
                )
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        for stream, level, channel in (
            (process.stdout, logging.INFO, "stdout"),
            (process.stderr, logging.WARNING, "stderr"),
        ):
            threading.Thread(
                target=reader,
                args=(stream, level, channel),
                name=f"opencode-server-{channel}-{process.pid}",
                daemon=True,
            ).start()

    def _wait_until_ready(
        self,
        client: OpenCodeClient,
        process: subprocess.Popen[str],
    ) -> None:
        deadline = time.monotonic() + self.startup_timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                raise OpenCodeManagerError("Создание сервера отменено")
            if process.poll() is not None:
                raise OpenCodeManagerError(
                    f"OpenCode завершился во время запуска (код {process.returncode})"
                )
            try:
                health = client.health(timeout=min(0.8, self._remaining(deadline)))
                if health.healthy:
                    return
                last_error = OpenCodeManagerError("health check вернул healthy=false")
            except Exception as exc:
                last_error = exc
            time.sleep(0.15)
        raise OpenCodeManagerError(
            f"OpenCode не прошёл health check за {self.startup_timeout:g} с: {last_error}"
        )

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OpenCodeManagerError("Истёк timeout подключения")
        return max(0.1, remaining)

    @staticmethod
    def _timeout_value(value: float) -> float:
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError("OpenCode timeout должен быть положительным конечным числом")
        return max(0.1, parsed)

    def _create_failed(
        self,
        message: str,
        cause: Optional[BaseException] = None,
        *,
        version: str = "",
    ) -> OpenCodeClient:
        self._set_status("error", message, version=version)
        error = OpenCodeManagerError(message)
        if cause is not None:
            raise error from cause
        raise error

    def _clear_connection(
        self,
        *,
        terminate_owned: bool,
        set_stopped: bool,
    ) -> None:
        with self._lock:
            process = self._process if terminate_owned and self._ownership == "owned" else None
            address = self._status.address or self.server_url
            self._stopping = True
            self._client = None
            if terminate_owned:
                self._process = None
            self._ownership = "none"
        try:
            self._terminate_process(process)
        finally:
            with self._lock:
                self._stopping = False
            if set_stopped:
                self._set_status(
                    "stopped",
                    "OpenCode Server отключён",
                    address=address,
                )

    def _start_exit_monitor(
        self,
        process: subprocess.Popen[str],
        generation: int,
    ) -> None:
        def monitor() -> None:
            return_code = process.wait()
            with self._lock:
                if (
                    not self._stopping
                    and generation == self._generation
                    and self._process is process
                ):
                    previous = self._status
                    self._client = None
                    self._set_status_locked(
                        ManagerStatus(
                            "error",
                            f"Созданный OpenCode аварийно завершился с кодом {return_code}",
                            version=previous.version,
                            address=previous.address,
                            pid=process.pid,
                            ownership="owned",
                            runtime_dir=str(self.runtime_dir),
                        )
                    )

        threading.Thread(
            target=monitor,
            name="opencode-process-monitor",
            daemon=True,
        ).start()

    @staticmethod
    def _terminate_process(process: Optional[subprocess.Popen[str]]) -> None:
        if process is None or process.poll() is not None:
            return
        pid = process.pid
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(pid, signal.SIGKILL)
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
        _log.info("server process stopped pid=%s", pid)

    def _set_status(
        self,
        state: str,
        message: str,
        *,
        version: str = "",
        address: str = "",
        pid: Optional[int] = None,
        agent_loaded: bool = False,
        ownership: str = "none",
    ) -> None:
        with self._lock:
            self._set_status_locked(
                ManagerStatus(
                    state,
                    message,
                    version=version,
                    address=address,
                    pid=pid,
                    agent_loaded=agent_loaded,
                    ownership=ownership,
                    runtime_dir=str(self.runtime_dir),
                )
            )

    @staticmethod
    def _safe_status_message(message: str) -> str:
        return re.sub(r"[\r\n\x00-\x1f]+", " ", str(message))[:2000]

    def _set_status_locked(self, status: ManagerStatus) -> None:
        safe = ManagerStatus(
            status.state,
            self._safe_status_message(status.message),
            status.version,
            status.address,
            status.pid,
            status.agent_loaded,
            status.ownership,
            status.runtime_dir,
        )
        self._status = safe
        level = logging.ERROR if safe.state == "error" else logging.INFO
        _log.log(
            level,
            "state=%s ownership=%s address=%s message=%s",
            safe.state,
            safe.ownership,
            safe.address,
            safe.message,
        )
