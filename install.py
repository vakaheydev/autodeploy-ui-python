"""Bootstrap installer; requires only the Python standard library."""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from pathlib import Path

from launcher.envfile import update_env
from launcher.installer import ReleaseInstaller
from launcher.paths import InstallPaths, default_install_root
from launcher.runtime import LauncherRuntime


def bootstrap_launcher(paths: InstallPaths, source_root: Path) -> None:
    """Install the dependency-free launcher outside versioned app directories."""
    paths.ensure()
    source = source_root / "launcher"
    destination = paths.root / "launcher"
    if source.resolve() != destination.resolve():
        staging = paths.root / ".launcher-bootstrap"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging)
        backup = paths.root / ".launcher-previous"
        if backup.exists():
            shutil.rmtree(backup)
        moved_previous = False
        try:
            if destination.exists():
                os.replace(destination, backup)
                moved_previous = True
            os.replace(staging, destination)
        except Exception:
            if not destination.exists() and moved_previous and backup.exists():
                os.replace(backup, destination)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    python = Path(sys.executable).resolve()
    command = paths.root / "Gravitee AutoDeploy.cmd"
    command.write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        f'\"{python}\" -m launcher --root \"{paths.root}\" gui\r\n'
        "if errorlevel 1 pause\r\n",
        encoding="utf-8",
    )
    shell = paths.root / "gravitee-autodeploy"
    shell.write_text(
        "#!/bin/sh\n"
        f'exec \"{python}\" -m launcher --root \"{paths.root}\" gui\n',
        encoding="utf-8",
    )
    try:
        shell.chmod(0o700)
    except OSError:
        pass


def console_install(paths: InstallPaths, bundle: Path | None) -> bool:
    token = getpass.getpass("TFS token (не отображается, Enter — оставить текущий): ").strip()
    if token:
        update_env(paths.env_file, {"TFS_TOKEN": token})
    if bundle:
        print(f"Устанавливаю {bundle.name}…")
        version = ReleaseInstaller(paths, on_status=print).install_bundle(bundle)
        print(f"Версия {version} установлена")
    answer = input("Запустить Gravitee AutoDeploy сейчас? [Y/n] ").strip().casefold()
    return answer not in {"n", "no", "н", "нет"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gravitee AutoDeploy installer")
    parser.add_argument("--root", type=Path, default=default_install_root())
    parser.add_argument("--bundle", type=Path, default=None)
    parser.add_argument("--console", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    args = parser.parse_args(argv)
    source_root = Path(__file__).resolve().parent
    default_bundle = source_root / "release-bundle.zip"
    bundle = Path(args.bundle).resolve() if args.bundle else (default_bundle if default_bundle.is_file() else None)
    paths = InstallPaths.create(args.root)
    bootstrap_launcher(paths, source_root)
    start = False
    if args.console:
        start = console_install(paths, bundle)
    else:
        try:
            from launcher.gui import run_launcher_gui

            start = run_launcher_gui(paths, bundle)
        except Exception as exc:
            print(f"Графический installer недоступен ({exc}); использую консоль.")
            start = console_install(paths, bundle)
    print(f"Launcher установлен в {paths.root}")
    if start and not args.no_start:
        return LauncherRuntime(paths, on_status=print).launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
