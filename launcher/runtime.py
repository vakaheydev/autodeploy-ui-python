from __future__ import annotations

import json
import logging
import logging.handlers
import os
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from launcher import __version__ as launcher_version
from launcher.envfile import read_env
from launcher.installer import ReleaseInstaller
from launcher.manifest import ReleaseManifest, version_key
from launcher.paths import InstallPaths
from launcher.provider import UpdateProvider, load_update_provider


_log = logging.getLogger("autodeploy.launcher")


def configure_launcher_logging(paths: InstallPaths) -> Path:
    paths.ensure()
    target = paths.logs / "launcher.log"
    root = logging.getLogger("autodeploy.launcher")
    root.setLevel(logging.INFO)
    if not any(isinstance(item, logging.handlers.RotatingFileHandler) and getattr(item, "baseFilename", "") == str(target) for item in root.handlers):
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=2 * 1024 * 1024, backupCount=4, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    return target


@dataclass(frozen=True)
class UpdateCheck:
    current_version: str | None
    manifest: ReleaseManifest
    update_available: bool


class LauncherRuntime:
    def __init__(
        self,
        paths: InstallPaths,
        *,
        on_status: Callable[[str], None] | None = None,
        provider: UpdateProvider | None = None,
    ) -> None:
        self.paths = paths
        self.on_status = on_status or (lambda _message: None)
        self.installer = ReleaseInstaller(paths, on_status=self.on_status)
        self._provider = provider
        configure_launcher_logging(paths)

    def check_update(self) -> UpdateCheck:
        provider = self._provider or load_update_provider(self.paths)
        manifest = provider.fetch_manifest()
        if version_key(manifest.minimum_launcher_version) > version_key(launcher_version):
            raise RuntimeError(
                f"Для обновления нужен launcher {manifest.minimum_launcher_version} или новее"
            )
        current = self.installer.state().current
        return UpdateCheck(current, manifest, manifest.newer_than(current))

    def install_update(self, check: UpdateCheck) -> str:
        if not check.update_available:
            return check.current_version or check.manifest.version
        provider = self._provider or load_update_provider(self.paths)
        bundle = self.paths.downloads / f"gravitee-autodeploy-{check.manifest.version}.zip"
        provider.download(check.manifest, bundle, self._download_progress)
        return self.installer.install_bundle(bundle, expected=check.manifest)

    def launch(self, *, open_browser: bool = True, rollback_on_failure: bool = True) -> int:
        values = read_env(self.paths.env_file)
        port = self._port(values.get("AUTODEPLOY_PORT", "8765"))
        url = f"http://127.0.0.1:{port}"
        existing = self.health(url, timeout=1.5)
        if existing:
            self._status(f"Сервер уже работает: {url}")
            if open_browser:
                webbrowser.open(url)
            return 0
        return self._start_current(url, port, open_browser, rollback_on_failure)

    def _start_current(
        self, url: str, port: int, open_browser: bool, rollback_on_failure: bool
    ) -> int:
        state_before = self.installer.state()
        python = self.installer.current_python()
        environment = os.environ.copy()
        environment.update({
            "AUTODEPLOY_HOST": "127.0.0.1",
            "AUTODEPLOY_PORT": str(port),
            "AUTODEPLOY_OPEN_BROWSER": "false",
            "AUTODEPLOY_ENV_FILE": str(self.paths.env_file),
            "AUTODEPLOY_DATA_DIR": str(self.paths.data),
            "AUTODEPLOY_LOG_DIR": str(self.paths.logs),
            "PYTHONUNBUFFERED": "1",
        })
        self._status(f"Запускаю Gravitee AutoDeploy {state_before.current} на {url}…")
        process = subprocess.Popen([str(python), "-m", "webapp"], env=environment)
        try:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                return_code = process.poll()
                if return_code is not None:
                    raise RuntimeError(f"Сервер завершился при старте с кодом {return_code}")
                if self.health(url, timeout=1.0):
                    self._status(f"Сервер готов: {url}")
                    if open_browser:
                        webbrowser.open(url)
                    return process.wait()
                time.sleep(0.25)
            raise TimeoutError("Сервер не прошёл health check за 30 секунд")
        except KeyboardInterrupt:
            process.terminate()
            try:
                return process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                return process.wait()
        except Exception:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            _log.exception("server startup failed version=%s", state_before.current)
            if rollback_on_failure and state_before.previous:
                rolled_back = self.installer.rollback()
                self._status(f"Новая версия не запустилась. Возвращаю {rolled_back}…")
                return self._start_current(url, port, open_browser, False)
            raise

    @staticmethod
    def health(url: str, *, timeout: float) -> dict[str, object] | None:
        request = urllib.request.Request(
            f"{url}/api/v1/health", headers={"Accept": "application/json"}, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    return None
                payload = json.loads(response.read(64 * 1024).decode("utf-8"))
                if payload.get("service") != "gravitee-autodeploy-web":
                    return None
                return payload
        except (OSError, ValueError, urllib.error.URLError):
            return None

    @staticmethod
    def _port(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("AUTODEPLOY_PORT должен быть числом") from exc
        if not 1 <= value <= 65535:
            raise ValueError("AUTODEPLOY_PORT должен быть от 1 до 65535")
        return value

    def _download_progress(self, label: str, received: int, total: int | None) -> None:
        if total:
            self._status(f"{label}: {received * 100 // total}%")
        else:
            self._status(f"{label}: {received // (1024 * 1024)} МБ")

    def _status(self, message: str) -> None:
        _log.info("%s", message)
        self.on_status(message)
