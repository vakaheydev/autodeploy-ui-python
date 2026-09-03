"""Жизненный цикл локального процесса ``opencode serve``."""
from __future__ import annotations

import atexit
import os
import re
import signal
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from opencode_integration.client import (
    OpenCodeAgentMissingError,
    OpenCodeClient,
    OpenCodeError,
)

OPENCODE_HOST = "127.0.0.1"
FORM_EXTRACTOR_AGENT = "form-extractor"
TARGET_OPENCODE_VERSION = "1.18.18"


class OpenCodeManagerError(OpenCodeError):
    """OpenCode нельзя запустить безопасным способом."""


@dataclass(frozen=True)
class ManagerStatus:
    state: str
    message: str
    version: str = ""
    address: str = ""
    pid: Optional[int] = None
    agent_loaded: bool = False


class OpenCodeManager:
    """Запускает ровно один localhost-only OpenCode Server на свободном порту."""

    def __init__(
        self,
        project_dir: Path,
        *,
        command: str = "opencode",
        startup_timeout: float = 20.0,
        request_timeout: float = 120.0,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.command = command
        self.startup_timeout = float(startup_timeout)
        self.request_timeout = float(request_timeout)
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._startup_cancel = threading.Event()
        self._process: Optional[subprocess.Popen[str]] = None
        self._client: Optional[OpenCodeClient] = None
        self._status = ManagerStatus("stopped", "OpenCode не запущен")
        self._stopping = False
        self._desired_running = False
        self._generation = 0
        atexit.register(self.stop)

    @property
    def client(self) -> Optional[OpenCodeClient]:
        with self._lock:
            return self._client if self.is_ready else None

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return (
                self._status.state == "ready"
                and self._process is not None
                and self._process.poll() is None
                and self._client is not None
            )

    @property
    def status(self) -> ManagerStatus:
        with self._lock:
            if self._process is not None and self._process.poll() is not None:
                if self._status.state == "ready" and not self._stopping:
                    self._status = ManagerStatus(
                        "error",
                        f"OpenCode аварийно завершился с кодом {self._process.returncode}",
                        version=self._status.version,
                        address=self._status.address,
                        pid=self._process.pid,
                    )
            return self._status

    def start(self) -> OpenCodeClient:
        """Синхронный start; вызывать только из worker thread."""
        with self._lock:
            self._desired_running = True
        return self._start_requested()

    def _start_requested(self) -> OpenCodeClient:
        """Выполняет уже зарегистрированный start request."""
        with self._lifecycle_lock:
            with self._lock:
                if not self._desired_running:
                    raise OpenCodeManagerError("Запуск OpenCode отменён")
                self._startup_cancel.clear()
            if self.is_ready:
                with self._lock:
                    assert self._client is not None
                    return self._client
            self._detach_and_terminate(set_stopped=False)
            with self._lock:
                self._status = ManagerStatus("starting", "Проверяю OpenCode...")

            executable = shutil.which(self.command)
            if executable is None:
                with self._lock:
                    self._status = ManagerStatus(
                        "error",
                        "Команда 'opencode' не найдена в PATH. Установите OpenCode 1.18.18.",
                    )
                    message = self._status.message
                raise OpenCodeManagerError(message)

            try:
                version = self._detect_version(executable)
            except Exception as exc:
                with self._lock:
                    self._status = ManagerStatus(
                        "error", f"Не удалось проверить версию OpenCode: {exc}"
                    )
                    message = self._status.message
                raise OpenCodeManagerError(message) from exc
            with self._lock:
                self._status = ManagerStatus(
                    "starting", f"Запускаю OpenCode {version}...", version=version
                )

            last_error: Optional[Exception] = None
            for _attempt in range(3):
                try:
                    port = self._pick_free_port()
                    address = f"http://{OPENCODE_HOST}:{port}"
                    process = self._spawn(executable, port)
                    with self._lock:
                        self._process = process
                        self._generation += 1
                        generation = self._generation
                    client = OpenCodeClient(address, timeout=self.request_timeout)
                    self._wait_until_ready(client, process)
                    client.require_agent(
                        FORM_EXTRACTOR_AGENT,
                        timeout=min(5.0, max(0.5, self.startup_timeout)),
                    )
                    if self._startup_cancel.is_set():
                        raise OpenCodeManagerError("Запуск OpenCode отменён")
                    with self._lock:
                        self._client = client
                        self._status = ManagerStatus(
                            "ready",
                            "OpenCode готов к AI-автозаполнению",
                            version=version,
                            address=address,
                            pid=process.pid,
                            agent_loaded=True,
                        )
                    self._start_exit_monitor(process, generation)
                    return client
                except Exception as exc:
                    last_error = exc
                    self._detach_and_terminate(set_stopped=False)
                    if self._startup_cancel.is_set() or isinstance(
                        exc, OpenCodeAgentMissingError
                    ):
                        break

            detail = str(last_error) if last_error else "неизвестная ошибка"
            with self._lock:
                self._status = ManagerStatus(
                    "error",
                    f"Не удалось запустить OpenCode Server: {detail}",
                    version=version,
                )
                message = self._status.message
            raise OpenCodeManagerError(message) from last_error

    def start_async(
        self,
        *,
        on_ready: Optional[Callable[[OpenCodeClient], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> threading.Thread:
        # Фиксируем намерение до запуска thread, чтобы последующий stop() мог
        # отменить даже worker, который ещё не успел получить lifecycle lock.
        with self._lock:
            self._desired_running = True

        def worker() -> None:
            try:
                client = self._start_requested()
            except Exception as exc:
                if on_error is not None:
                    on_error(exc)
            else:
                if on_ready is not None:
                    on_ready(client)

        thread = threading.Thread(target=worker, name="opencode-startup", daemon=True)
        thread.start()
        return thread

    def restart(self) -> OpenCodeClient:
        self.stop()
        return self.start()

    def stop(self) -> None:
        with self._lock:
            self._desired_running = False
            self._startup_cancel.set()
        with self._lifecycle_lock:
            self._detach_and_terminate(set_stopped=True)

    def _detach_and_terminate(self, *, set_stopped: bool) -> None:
        with self._lock:
            process = self._process
            self._stopping = True
            self._process = None
            self._client = None
        try:
            self._terminate_process(process)
        finally:
            with self._lock:
                self._stopping = False
                if set_stopped:
                    self._status = ManagerStatus("stopped", "OpenCode остановлен")

    def _detect_version(self, executable: str) -> str:
        try:
            completed = subprocess.run(
                [executable, "--version"],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise OpenCodeManagerError(f"Не удалось выполнить opencode --version: {exc}") from exc
        combined = f"{completed.stdout}\n{completed.stderr}".strip()
        if completed.returncode != 0:
            raise OpenCodeManagerError(
                f"opencode --version завершился с кодом {completed.returncode}"
            )
        match = re.search(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", combined)
        if not match:
            raise OpenCodeManagerError("Не удалось определить версию OpenCode")
        return match.group(0)

    @staticmethod
    def _pick_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((OPENCODE_HOST, 0))
            return int(sock.getsockname()[1])

    def _spawn(self, executable: str, port: int) -> subprocess.Popen[str]:
        kwargs = {
            "cwd": str(self.project_dir),
            "stdin": subprocess.DEVNULL,
            # Не сохраняем stdout: сервер/провайдер потенциально может вывести
            # чувствительный контекст заявки. Диагностика идёт через HTTP/status.
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(
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

    def _wait_until_ready(self, client: OpenCodeClient, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + self.startup_timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            if self._startup_cancel.is_set():
                raise OpenCodeManagerError("Запуск OpenCode отменён")
            if process.poll() is not None:
                raise OpenCodeManagerError(
                    f"OpenCode завершился во время запуска (код {process.returncode})"
                )
            try:
                health = client.health(timeout=0.8)
                if health.healthy:
                    return
                last_error = OpenCodeManagerError("health check вернул healthy=false")
            except Exception as exc:
                last_error = exc
            time.sleep(0.15)
        raise OpenCodeManagerError(
            f"OpenCode не прошёл health check за {self.startup_timeout:.0f} с: {last_error}"
        )

    def _start_exit_monitor(self, process: subprocess.Popen[str], generation: int) -> None:
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
                    self._status = ManagerStatus(
                        "error",
                        f"OpenCode аварийно завершился с кодом {return_code}",
                        version=previous.version,
                        address=previous.address,
                        pid=process.pid,
                    )

        threading.Thread(target=monitor, name="opencode-monitor", daemon=True).start()

    @staticmethod
    def _terminate_process(process: Optional[subprocess.Popen[str]]) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                # Процесс запущен в отдельной session: завершаем и возможных
                # дочерних provider-процессов, чтобы ничего не осталось висеть.
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                return
            try:
                process.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                pass
        except OSError:
            pass
