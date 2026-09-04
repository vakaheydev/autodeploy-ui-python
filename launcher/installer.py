from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import time
import venv
import zipfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from launcher.manifest import ReleaseManifest, version_key
from launcher.paths import InstallPaths


_log = logging.getLogger("autodeploy.launcher.install")
StatusCallback = Callable[[str], None]
_MAX_ARCHIVE_FILES = 20_000
_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class InstallState:
    current: str | None
    previous: str | None
    installed_at: float | None


class UpdateLock(AbstractContextManager["UpdateLock"]):
    def __init__(self, path: Path, stale_after: float = 1800.0) -> None:
        self.path = path
        self.stale_after = stale_after
        self.acquired = False

    def __enter__(self) -> "UpdateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    age = 0
                if attempt == 0 and age > self.stale_after:
                    self.path.unlink(missing_ok=True)
                    continue
                raise RuntimeError("Другая установка или обновление уже выполняется")
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(json.dumps({"pid": os.getpid(), "created_at": time.time()}))
                self.acquired = True
                return self
        raise RuntimeError("Не удалось получить update lock")

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


class ReleaseInstaller:
    def __init__(
        self,
        paths: InstallPaths,
        *,
        python_executable: str | Path = sys.executable,
        on_status: StatusCallback | None = None,
    ) -> None:
        self.paths = paths
        self.python_executable = str(python_executable)
        self.on_status = on_status or (lambda _message: None)
        paths.ensure()

    def state(self) -> InstallState:
        if not self.paths.state_file.is_file():
            return InstallState(None, None, None)
        try:
            raw = json.loads(self.paths.state_file.read_text(encoding="utf-8"))
            current = raw.get("current")
            previous = raw.get("previous")
            installed_at = raw.get("installed_at")
            if current is not None:
                version_key(str(current))
            if previous is not None:
                version_key(str(previous))
            return InstallState(
                str(current) if current else None,
                str(previous) if previous else None,
                float(installed_at) if installed_at else None,
            )
        except Exception as exc:
            raise RuntimeError("Повреждён current.json launcher") from exc

    def installed_versions(self) -> list[str]:
        values: list[str] = []
        if not self.paths.versions.is_dir():
            return values
        for item in self.paths.versions.iterdir():
            if item.is_dir() and (item / "installed.json").is_file():
                try:
                    version_key(item.name)
                except ValueError:
                    continue
                values.append(item.name)
        return sorted(values, key=version_key, reverse=True)

    def install_bundle(
        self,
        bundle: Path,
        *,
        expected: ReleaseManifest | None = None,
        reinstall: bool = False,
    ) -> str:
        bundle = Path(bundle).expanduser().resolve()
        if not bundle.is_file():
            raise FileNotFoundError(f"Release bundle не найден: {bundle}")
        with UpdateLock(self.paths.lock_file):
            self._status("Проверяю архив обновления…")
            if expected is not None:
                self._verify_expected_bundle(bundle, expected)
            metadata = self._read_metadata(bundle)
            version = str(metadata["version"])
            if expected and version != expected.version:
                raise ValueError(
                    f"Версия bundle {version} не совпадает с manifest {expected.version}"
                )
            target = self.paths.versions / version
            if target.is_dir() and (target / "installed.json").is_file() and not reinstall:
                self._activate(version)
                return version
            staging = self.paths.versions / f".staging-{version}-{secrets.token_hex(6)}"
            backup: Path | None = None
            target_created = False
            try:
                staging.mkdir(parents=False, exist_ok=False)
                self._extract_safely(bundle, staging)
                self._check_runtime(metadata)

                # A virtual environment is not portable: its launchers and
                # entry points contain absolute paths.  Therefore only the
                # extracted, inert release payload is staged.  The venv is
                # created after an atomic move to the final version path.
                if target.exists():
                    backup = self.paths.versions / (
                        f".replaced-{version}-{int(time.time())}-{secrets.token_hex(4)}"
                    )
                    os.replace(target, backup)
                os.replace(staging, target)
                target_created = True

                self._status(f"Создаю изолированное Python-окружение {version}…")
                environment = target / ".venv"
                venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(environment)
                python = self.python_in(environment)
                wheels = sorted((target / "packages").glob("*.whl"))
                if not wheels:
                    raise ValueError("В release bundle отсутствуют packages/*.whl")
                wheelhouse = target / "wheelhouse"
                command = [
                    str(python), "-m", "pip", "install",
                    "--disable-pip-version-check", "--no-index",
                    "--find-links", str(wheelhouse),
                    *[str(path) for path in wheels],
                ]
                self._status("Устанавливаю проверенные Python-пакеты офлайн…")
                self._run(command, timeout=600)
                self._status("Проверяю запуск новой версии…")
                smoke_environment = os.environ.copy()
                smoke_environment.update({
                    "AUTODEPLOY_ENV_FILE": str(self.paths.env_file),
                    "AUTODEPLOY_DATA_DIR": str(self.paths.data),
                    "AUTODEPLOY_LOG_DIR": str(self.paths.logs),
                    "AUTODEPLOY_OPENCODE_AUTO_CONNECT": "false",
                })
                self._smoke(python, smoke_environment)
                marker = {
                    "version": version,
                    "installed_at": time.time(),
                    "bundle": bundle.name,
                }
                (target / "installed.json").write_text(
                    json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self._install_launcher_payload(target)
                self._activate(version)
                if backup is not None:
                    shutil.rmtree(backup, ignore_errors=True)
                self._status(f"Версия {version} установлена")
                return version
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                if target_created and target.exists():
                    failed = self.paths.versions / (
                        f".failed-{version}-{int(time.time())}-{secrets.token_hex(4)}"
                    )
                    try:
                        os.replace(target, failed)
                    except OSError:
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        shutil.rmtree(failed, ignore_errors=True)
                if backup is not None and backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise

    @staticmethod
    def _verify_expected_bundle(bundle: Path, expected: ReleaseManifest) -> None:
        actual_size = bundle.stat().st_size
        if expected.size is not None and actual_size != expected.size:
            raise ValueError(
                f"Размер release bundle не совпал: ожидалось {expected.size}, "
                f"получено {actual_size}"
            )
        digest = hashlib.sha256()
        with bundle.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(), expected.sha256):
            raise ValueError("SHA-256 release bundle не совпадает с manifest")

    def _install_launcher_payload(self, staging: Path) -> None:
        source = staging / "launcher_payload" / "launcher"
        if not source.is_dir():
            return
        destination = self.paths.root / "launcher"
        upcoming = self.paths.root / ".launcher-next"
        previous = self.paths.root / ".launcher-previous"
        if upcoming.exists():
            shutil.rmtree(upcoming)
        shutil.copytree(source, upcoming)
        if previous.exists():
            shutil.rmtree(previous)
        moved_previous = False
        try:
            if destination.exists():
                os.replace(destination, previous)
                moved_previous = True
            os.replace(upcoming, destination)
        except Exception:
            # Updating the launcher is part of the same install transaction.
            # Never leave the stable entry point missing after a failed rename.
            if not destination.exists() and moved_previous and previous.exists():
                os.replace(previous, destination)
            raise
        finally:
            if upcoming.exists():
                shutil.rmtree(upcoming, ignore_errors=True)

    def rollback(self) -> str:
        with UpdateLock(self.paths.lock_file):
            state = self.state()
            candidate = state.previous
            if not candidate:
                versions = [item for item in self.installed_versions() if item != state.current]
                candidate = versions[0] if versions else None
            if not candidate or not (self.paths.versions / candidate / "installed.json").is_file():
                raise RuntimeError("Предыдущая рабочая версия не найдена")
            self._write_state(candidate, state.current)
            self._status(f"Выполнен rollback на {candidate}")
            return candidate

    def current_python(self) -> Path:
        state = self.state()
        if not state.current:
            raise RuntimeError("Приложение ещё не установлено")
        environment = self.paths.versions / state.current / ".venv"
        python = self.python_in(environment)
        if not python.is_file():
            raise RuntimeError(f"Python environment версии {state.current} повреждён")
        return python

    @staticmethod
    def python_in(environment: Path) -> Path:
        return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _activate(self, version: str) -> None:
        state = self.state()
        previous = state.current if state.current != version else state.previous
        self._write_state(version, previous)

    def _write_state(self, current: str, previous: str | None) -> None:
        payload = {
            "schema_version": 1,
            "current": current,
            "previous": previous,
            "installed_at": time.time(),
        }
        temporary = self.paths.state_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.paths.state_file)

    def _read_metadata(self, bundle: Path) -> dict[str, object]:
        with zipfile.ZipFile(bundle) as archive:
            self._validate_archive(archive)
            try:
                payload = archive.read("release.json")
            except KeyError as exc:
                raise ValueError("В release bundle отсутствует release.json") from exc
        if len(payload) > 1024 * 1024:
            raise ValueError("release.json превышает 1 МБ")
        raw = json.loads(payload.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("release.json должен быть объектом")
        allowed = {
            "schema_version", "version", "python_requires", "python_versions",
            "target_platform", "built_at", "commit",
        }
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError("Неизвестные поля release.json: " + ", ".join(sorted(unknown)))
        if int(raw.get("schema_version", 0)) != 1:
            raise ValueError("Неподдерживаемая схема release bundle")
        version_key(str(raw.get("version", "")))
        return raw

    @staticmethod
    def _validate_archive(archive: zipfile.ZipFile) -> None:
        infos = archive.infolist()
        if len(infos) > _MAX_ARCHIVE_FILES:
            raise ValueError("Слишком много файлов в release bundle")
        total = 0
        for info in infos:
            total += info.file_size
            if total > _MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Распакованный release bundle превышает 2 ГБ")
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"Небезопасный путь внутри release bundle: {info.filename!r}")
            if ":" in path.parts[0] or "\\" in info.filename:
                raise ValueError(f"Небезопасный путь внутри release bundle: {info.filename!r}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("Symbolic links запрещены в release bundle")

    def _extract_safely(self, bundle: Path, destination: Path) -> None:
        with zipfile.ZipFile(bundle) as archive:
            self._validate_archive(archive)
            for info in archive.infolist():
                target = destination.joinpath(*PurePosixPath(info.filename).parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

    @staticmethod
    def _check_runtime(metadata: dict[str, object]) -> None:
        requirement = str(metadata.get("python_requires", ">=3.10,<3.14"))
        current = sys.version_info[:2]
        if current < (3, 10) or current >= (3, 14):
            raise RuntimeError(
                f"Нужен Python {requirement}; обнаружен {sys.version_info.major}.{sys.version_info.minor}"
            )
        supported = metadata.get("python_versions")
        current_tag = f"{current[0]}{current[1]}"
        if isinstance(supported, list) and supported and current_tag not in {
            str(item).replace(".", "") for item in supported
        }:
            raise RuntimeError(
                "Release не содержит wheels для Python "
                f"{current[0]}.{current[1]}; доступны: {', '.join(map(str, supported))}"
            )
        target = str(metadata.get("target_platform", "")).casefold()
        if target:
            if target.startswith("win") and os.name != "nt":
                raise RuntimeError(f"Этот release собран для Windows ({target})")
            if target.startswith("linux") and not sys.platform.startswith("linux"):
                raise RuntimeError(f"Этот release собран для Linux ({target})")
            current_machine = platform.machine().casefold().replace("-", "_")
            target_machine = target.replace("-", "_")
            x64_names = {"amd64", "x86_64"}
            if any(name in target_machine for name in x64_names) and current_machine not in x64_names:
                raise RuntimeError(
                    f"Release {target} несовместим с архитектурой {platform.machine()}"
                )

    def _run(
        self,
        command: list[str],
        *,
        timeout: float,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            # Never run smoke checks from the source checkout: otherwise an
            # import can succeed even when the wheel is incomplete.
            cwd=cwd or self.paths.root,
            check=False,
        )
        if process.returncode != 0:
            output = process.stdout[-8000:]
            raise RuntimeError(f"Команда установки завершилась с кодом {process.returncode}:\n{output}")

    def _smoke(self, python: Path, environment: dict[str, str]) -> None:
        self._run(
            [
                str(python), "-c",
                "import webapp; from webapp.app import create_app; "
                "assert webapp.__version__; assert create_app",
            ],
            timeout=60,
            env=environment,
            cwd=self.paths.root,
        )

    def _status(self, message: str) -> None:
        _log.info("%s", message)
        self.on_status(message)
