from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from launcher.envfile import read_env, update_env
from launcher.gui import run_launcher_gui
from launcher.installer import ReleaseInstaller
from launcher.paths import InstallPaths, default_install_root
from launcher.runtime import LauncherRuntime, configure_launcher_logging


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="gravitee-autodeploy-launcher")
    value.add_argument("--root", type=Path, default=default_install_root())
    commands = value.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure", help="Сохранить TFS token")
    configure.add_argument("--manifest-url", default="", help=argparse.SUPPRESS)
    install = commands.add_parser("install", help="Установить локальный release bundle")
    install.add_argument("bundle", type=Path)
    update = commands.add_parser("update", help="Проверить и установить обновление")
    update.add_argument("--yes", action="store_true")
    run = commands.add_parser("run", help="Проверить обновление и запустить сервер")
    run.add_argument("--skip-update", action="store_true")
    run.add_argument("--yes", action="store_true", help="Устанавливать найденное обновление без вопроса")
    run.add_argument("--no-browser", action="store_true")
    commands.add_parser("status", help="Показать состояние установки")
    commands.add_parser("rollback", help="Вернуться к предыдущей установленной версии")
    commands.add_parser("gui", help="Открыть графический launcher")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    paths = InstallPaths.create(args.root)
    paths.ensure()
    configure_launcher_logging(paths)
    installer = ReleaseInstaller(paths, on_status=print)
    if args.command == "configure":
        token = getpass.getpass("TFS token (не отображается): ").strip()
        updates = {"TFS_TOKEN": token}
        if args.manifest_url:
            updates["AUTODEPLOY_UPDATE_MANIFEST_URL"] = args.manifest_url
        update_env(paths.env_file, updates)
        print(f"Настройки сохранены: {paths.env_file}")
        return 0
    if args.command == "install":
        print(f"Установлена версия {installer.install_bundle(args.bundle)}")
        return 0
    if args.command == "status":
        state = installer.state()
        print(json.dumps({
            "root": str(paths.root),
            "current": state.current,
            "previous": state.previous,
            "installed_versions": installer.installed_versions(),
            "tfs_token_configured": bool(read_env(paths.env_file).get("TFS_TOKEN")),
            "launcher_log": str(paths.logs / "launcher.log"),
            "server_log": str(paths.logs / "autodeploy.log"),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "rollback":
        print(f"Активирована версия {installer.rollback()}")
        return 0
    if args.command == "gui":
        if run_launcher_gui(paths):
            return LauncherRuntime(paths, on_status=print).launch()
        return 0

    runtime = LauncherRuntime(paths, on_status=print)
    if args.command == "update":
        return _update(runtime, automatically=args.yes)
    if args.command == "run":
        if not args.skip_update:
            try:
                _update(runtime, automatically=args.yes, nonfatal=True)
            except Exception as exc:
                print(f"Проверка обновлений недоступна: {exc}", file=sys.stderr)
        return runtime.launch(open_browser=not args.no_browser)
    return 2


def _update(
    runtime: LauncherRuntime,
    *,
    automatically: bool,
    nonfatal: bool = False,
) -> int:
    try:
        check = runtime.check_update()
        if not check.update_available:
            print(f"Установлена актуальная версия {check.current_version}")
            return 0
        print(f"Доступна версия {check.manifest.version}\n\n{check.manifest.changelog}")
        approved = automatically
        if not approved and sys.stdin.isatty():
            approved = input("Установить обновление? [y/N] ").strip().casefold() in {"y", "yes", "д", "да"}
        if not approved:
            print("Обновление отложено")
            return 0
        version = runtime.install_update(check)
        print(f"Обновление {version} установлено")
        return 0
    except Exception:
        if not nonfatal:
            raise
        raise
