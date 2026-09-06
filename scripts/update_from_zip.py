r"""Replace a local checkout while preserving ``.env`` and ``.venv``.

Configure ``ARCHIVE_URL`` and ``TARGET_DIR`` below, copy this script outside the
directory being updated, stop AutoDeploy, and run it with a system Python:

    py.exe C:\path\outside\update_from_zip.py

The updater does not require ``requests``.  It downloads into a sibling
temporary directory, rejects unsafe ZIP entries, validates project markers,
copies the existing root ``.env`` into the staged version, moves ``.venv``
without copying it, and swaps the target directory. If the swap fails, the
previous directory is restored.
"""
from __future__ import annotations

import hashlib
import shutil
import stat
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath


# ---------------------------------------------------------------------------
# User configuration
# ---------------------------------------------------------------------------

# GitHub branch archive example. Any direct HTTPS URL returning a ZIP works.
ARCHIVE_URL = (
    "https://github.com/vakaheydev/autodeploy-ui-python/"
    "archive/refs/heads/web-platform.zip"
)

# The existing directory whose contents must be completely replaced.
TARGET_DIR = Path(r"C:\CHANGE_ME\gravitee-autodeploy")

# Optional SHA-256 of the expected ZIP. Leave empty for a moving branch archive.
# For reproducible releases, point ARCHIVE_URL to an immutable artifact and set
# its 64-character lowercase hash here.
EXPECTED_SHA256 = ""

# Files copied from the current target after the archive has been staged.
# Paths are relative to TARGET_DIR. The archive's versions are never retained.
PRESERVE_RELATIVE_PATHS = (Path(".env"), Path(".venv"))

# A correct public-core archive must contain these paths after its single
# GitHub-generated top-level directory has been removed.
EXPECTED_PROJECT_MARKERS = (Path("pyproject.toml"), Path("webapp"))

DOWNLOAD_TIMEOUT_SECONDS = 120
MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000

# False removes the old tree after a successful swap. During the swap it still
# exists and is restored automatically if activation fails. If True, it remains
# beside TARGET_DIR and may contain a copy of .env, so protect it accordingly.
# Preserved directories are copied in this optional mode so that both versions
# remain independently usable. With the default False they are moved instantly.
KEEP_BACKUP = False


class UpdateError(RuntimeError):
    """The archive cannot be installed safely."""


def _safe_relative_path(value: Path) -> Path:
    if value.is_absolute() or not value.parts:
        raise UpdateError(f"Некорректный относительный путь: {value}")
    if any(part in {"", ".", ".."} for part in value.parts):
        raise UpdateError(f"Некорректный относительный путь: {value}")
    return value


def _validate_configuration(target: Path) -> Path:
    parsed = urllib.parse.urlsplit(ARCHIVE_URL)
    if parsed.scheme != "https" or not parsed.hostname:
        raise UpdateError("ARCHIVE_URL должен быть прямым HTTPS URL")

    resolved = target.expanduser().resolve()
    if resolved.parent == resolved or resolved == Path.home().resolve():
        raise UpdateError("TARGET_DIR не может быть корнем диска или домашней папкой")
    if not resolved.parent.is_dir():
        raise UpdateError(f"Родительская папка TARGET_DIR не существует: {resolved.parent}")
    if "CHANGE_ME" in str(resolved):
        raise UpdateError("Сначала укажите реальный TARGET_DIR в начале скрипта")

    script = Path(__file__).resolve()
    executable = Path(sys.executable).resolve()
    for candidate, label in ((script, "Скрипт"), (executable, "Python")):
        try:
            candidate.relative_to(resolved)
        except ValueError:
            continue
        raise UpdateError(
            f"{label} находится внутри обновляемой папки. "
            "Запустите скрипт системным Python из другой папки"
        )

    for relative in (*PRESERVE_RELATIVE_PATHS, *EXPECTED_PROJECT_MARKERS):
        _safe_relative_path(relative)
    return resolved


def _download(url: str, destination: Path) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Gravitee-AutoDeploy-Zip-Updater/1.0"},
        method="GET",
    )
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(  # noqa: S310 - URL is validated as HTTPS
            request,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        ) as response, destination.open("wb") as output:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != "https":
                raise UpdateError("Сервер перенаправил загрузку на небезопасный URL")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_ARCHIVE_BYTES:
                    raise UpdateError(
                        f"ZIP превышает лимит {MAX_ARCHIVE_BYTES} байт"
                    )
                digest.update(chunk)
                output.write(chunk)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"Не удалось скачать ZIP: {exc}") from exc

    if received == 0:
        raise UpdateError("Сервер вернул пустой файл")
    return digest.hexdigest()


def _zip_member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if (
        not name
        or "\x00" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(":" in part for part in path.parts)
    ):
        raise UpdateError(f"ZIP содержит небезопасный путь: {info.filename!r}")
    mode = (info.external_attr >> 16) & 0o170000
    if stat.S_ISLNK(mode):
        raise UpdateError(f"ZIP содержит symbolic link: {info.filename!r}")
    return path


def _extract_safely(archive: Path, destination: Path) -> None:
    try:
        source = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"Загруженный файл не является корректным ZIP: {exc}") from exc

    with source:
        members = source.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            raise UpdateError(f"В ZIP слишком много файлов: {len(members)}")
        total = sum(max(0, member.file_size) for member in members)
        if total > MAX_EXTRACTED_BYTES:
            raise UpdateError(
                f"Распакованный ZIP превышает лимит {MAX_EXTRACTED_BYTES} байт"
            )

        root = destination.resolve()
        for member in members:
            relative = _zip_member_path(member)
            output = destination.joinpath(*relative.parts)
            try:
                output.resolve().relative_to(root)
            except ValueError as exc:
                raise UpdateError(
                    f"ZIP пытается записать файл вне staging: {member.filename!r}"
                ) from exc
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as incoming, output.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)


def _payload_root(extracted: Path) -> Path:
    children = list(extracted.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extracted


def _remove_staged_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _prepare_preserved_paths(
    current: Path,
    staged: Path,
    *,
    copy_directories: bool,
) -> tuple[Path, ...]:
    """Copy files and return directories that should be moved after the swap."""
    directories: list[Path] = []
    for relative in PRESERVE_RELATIVE_PATHS:
        old = current / relative
        new = staged / relative

        # Never accept the archive's version of a preserved configuration file.
        if new.exists() or new.is_symlink():
            _remove_staged_path(new)

        if not old.exists() and not old.is_symlink():
            continue
        if old.is_symlink():
            raise UpdateError(f"Сохраняемый путь не должен быть symbolic link: {old}")
        if old.is_file():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)
            continue
        if old.is_dir():
            if copy_directories:
                shutil.copytree(old, new)
            else:
                directories.append(relative)
            continue
        raise UpdateError(f"Неподдерживаемый сохраняемый путь: {old}")
    return tuple(directories)


def _move_preserved_directories(
    backup: Path,
    target: Path,
    directories: tuple[Path, ...],
) -> None:
    for relative in directories:
        source = backup / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)


def _restore_previous_target(
    target: Path,
    backup: Path,
    work: Path,
    directories: tuple[Path, ...],
) -> None:
    """Put moved directories back, discard staged activation, restore backup."""
    for relative in reversed(directories):
        live = target / relative
        previous = backup / relative
        if (live.exists() or live.is_symlink()) and not (
            previous.exists() or previous.is_symlink()
        ):
            previous.parent.mkdir(parents=True, exist_ok=True)
            live.rename(previous)

    if target.exists() or target.is_symlink():
        failed = work / "failed-activation"
        if failed.exists() or failed.is_symlink():
            _remove_staged_path(failed)
        target.rename(failed)
    backup.rename(target)


def replace_directory_from_zip(
    archive: Path,
    target: Path,
    *,
    keep_backup: bool = KEEP_BACKUP,
) -> Path | None:
    """Stage and activate ``archive``. Return a retained backup path, if any."""
    target = target.expanduser().resolve()
    work = Path(tempfile.mkdtemp(prefix=f".{target.name}-update-", dir=target.parent))
    extracted = work / "extracted"
    staged = work / "staged"
    extracted.mkdir()
    backup: Path | None = None
    activated = False
    preserved_directories: tuple[Path, ...] = ()
    try:
        _extract_safely(archive, extracted)
        payload = _payload_root(extracted)
        shutil.copytree(payload, staged)

        missing = [str(path) for path in EXPECTED_PROJECT_MARKERS if not (staged / path).exists()]
        if missing:
            raise UpdateError(
                "Архив не похож на Gravitee AutoDeploy, отсутствуют: "
                + ", ".join(missing)
            )

        if target.exists():
            if not target.is_dir() or target.is_symlink():
                raise UpdateError(f"TARGET_DIR должен быть обычной папкой: {target}")
            preserved_directories = _prepare_preserved_paths(
                target,
                staged,
                copy_directories=keep_backup,
            )
            suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = target.parent / f".{target.name}.backup-{suffix}"
            counter = 1
            while backup.exists():
                backup = target.parent / f".{target.name}.backup-{suffix}-{counter}"
                counter += 1
            target.rename(backup)

        try:
            staged.rename(target)
            activated = True
            if backup is not None:
                _move_preserved_directories(
                    backup,
                    target,
                    preserved_directories,
                )
        except Exception:
            if backup is not None and backup.exists():
                _restore_previous_target(
                    target,
                    backup,
                    work,
                    preserved_directories,
                )
                activated = False
            raise

        if backup is not None and not keep_backup:
            shutil.rmtree(backup)
            backup = None
        return backup
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"Не удалось заменить папку: {exc}") from exc
    finally:
        # After activation, ``staged`` has moved out of work. On any earlier
        # failure only temporary data is removed; the original target remains.
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        if not activated and backup is not None and backup.exists() and not target.exists():
            backup.rename(target)


def update() -> Path | None:
    target = _validate_configuration(TARGET_DIR)
    work = Path(tempfile.mkdtemp(prefix="autodeploy-download-"))
    archive = work / "source.zip"
    try:
        print(f"Скачиваю: {ARCHIVE_URL}")
        actual_hash = _download(ARCHIVE_URL, archive)
        print(f"ZIP загружен, SHA-256: {actual_hash}")
        expected = EXPECTED_SHA256.strip().casefold()
        if expected and actual_hash.casefold() != expected:
            raise UpdateError(
                f"SHA-256 не совпадает: ожидался {expected}, получен {actual_hash}"
            )

        print(f"Заменяю папку: {target}")
        backup = replace_directory_from_zip(archive, target)
        print("Обновление завершено. Текущие .env и .venv сохранены.")
        if backup is not None:
            print(f"Предыдущая версия оставлена: {backup}")
        return backup
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    try:
        update()
    except UpdateError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
