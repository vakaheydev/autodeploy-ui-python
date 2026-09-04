"""Build an offline, per-platform application bundle and bootstrap installer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run(command: list[str], cwd: Path = ROOT) -> None:
    process = subprocess.run(command, cwd=cwd, check=False)
    if process.returncode:
        raise SystemExit(process.returncode)


def read_version() -> tuple[str, str]:
    text = (ROOT / "version.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    first, _, changelog = text.partition("\n\n")
    version = first.strip()
    if not version:
        raise ValueError("version.txt: первая строка с версией пуста")
    return version, changelog.strip()


def add_tree(archive: zipfile.ZipFile, source: Path, prefix: str) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            relative = path.relative_to(source).as_posix()
            archive.write(path, f"{prefix.rstrip('/')}/{relative}".lstrip("/"))


def clean_python_build_cache() -> None:
    """Prevent removed package assets from leaking out of setuptools build/lib."""
    build_directory = (ROOT / "build").resolve()
    cached_library = (build_directory / "lib").resolve()
    if cached_library.parent != build_directory:
        raise ValueError(f"Unexpected build cache path: {cached_library}")
    if cached_library.exists():
        shutil.rmtree(cached_library)
    for candidate in build_directory.iterdir() if build_directory.is_dir() else ():
        if candidate.is_dir() and candidate.name.startswith("bdist."):
            shutil.rmtree(candidate)
    egg_info = (ROOT / "gravitee_autodeploy.egg-info").resolve()
    if egg_info.parent != ROOT:
        raise ValueError(f"Unexpected egg-info path: {egg_info}")
    if egg_info.exists():
        shutil.rmtree(egg_info)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--artifact-url", default="https://tfs.example.invalid/replace-me/release.zip")
    parser.add_argument("--extra-wheel", action="append", type=Path, default=[])
    parser.add_argument(
        "--wheel-platform",
        default="",
        help="pip target platform, for example win_amd64",
    )
    parser.add_argument(
        "--python-version",
        action="append",
        default=[],
        help="target CPython version without a dot, for example 312 (repeatable)",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "release")
    args = parser.parse_args()
    version, changelog = read_version()
    output = args.output.resolve()
    build_root = (ROOT / "build" / "release-work").resolve()
    for candidate in (output, build_root):
        if ROOT not in candidate.parents:
            raise ValueError(f"Build directory выходит за project root: {candidate}")
        if candidate.exists():
            shutil.rmtree(candidate)
        candidate.mkdir(parents=True)

    if not args.skip_frontend:
        run(["npm", "ci"], ROOT / "frontend")
        run(["npm", "run", "build"], ROOT / "frontend")
    if not (ROOT / "webapp" / "static" / "index.html").is_file():
        raise FileNotFoundError("React production build отсутствует")

    dist = build_root / "dist"
    clean_python_build_cache()
    run([sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)])
    app_wheels = sorted(dist.glob("gravitee_autodeploy-*.whl"))
    if len(app_wheels) != 1:
        raise RuntimeError("Не удалось однозначно найти application wheel")
    bundle_root = build_root / "bundle"
    packages = bundle_root / "packages"
    wheelhouse = bundle_root / "wheelhouse"
    packages.mkdir(parents=True)
    wheelhouse.mkdir(parents=True)
    shutil.copy2(app_wheels[0], packages / app_wheels[0].name)
    for extra in args.extra_wheel:
        extra = extra.expanduser().resolve()
        if extra.suffix != ".whl" or not extra.is_file():
            raise ValueError(f"Corporate extension wheel не найден: {extra}")
        shutil.copy2(extra, packages / extra.name)
    if not args.skip_download:
        requested_versions = args.python_version or [""]
        for python_version in requested_versions:
            command = [
                sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                "--dest", str(wheelhouse),
            ]
            if args.wheel_platform:
                command.extend(["--platform", args.wheel_platform, "--implementation", "cp"])
            if python_version:
                if not python_version.isdigit() or len(python_version) not in {2, 3}:
                    raise ValueError(f"Некорректный --python-version: {python_version!r}")
                command.extend(["--python-version", python_version])
            command.extend(["--requirement", str(ROOT / "requirements-web.txt")])
            run(command)
    commit = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    (bundle_root / "release.json").write_text(json.dumps({
        "schema_version": 1,
        "version": version,
        "python_requires": ">=3.10,<3.14",
        "python_versions": args.python_version or [f"{sys.version_info.major}{sys.version_info.minor}"],
        "target_platform": args.wheel_platform or f"{platform.system().lower()}_{platform.machine().lower()}",
        "built_at": time.time(),
        "commit": commit,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copytree(ROOT / "launcher", bundle_root / "launcher_payload" / "launcher")

    app_bundle = output / f"gravitee-autodeploy-app-{version}.zip"
    with zipfile.ZipFile(app_bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        add_tree(archive, bundle_root, "")
    digest = hashlib.sha256(app_bundle.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "version": version,
        "artifact_url": args.artifact_url,
        "sha256": digest,
        "size": app_bundle.stat().st_size,
        "changelog": changelog,
        "minimum_launcher_version": "1.0.0",
    }
    (output / "update-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    installer_stage = build_root / "installer"
    installer_stage.mkdir()
    for name in ("install.py", "install.cmd", "install.sh", "README.md"):
        shutil.copy2(ROOT / name, installer_stage / name)
    shutil.copytree(ROOT / "launcher", installer_stage / "launcher")
    shutil.copy2(app_bundle, installer_stage / "release-bundle.zip")
    installer_bundle = output / f"gravitee-autodeploy-installer-{version}.zip"
    with zipfile.ZipFile(installer_bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        add_tree(archive, installer_stage, "")
    print(json.dumps({
        "version": version,
        "app_bundle": str(app_bundle),
        "installer_bundle": str(installer_bundle),
        "manifest": str(output / "update-manifest.json"),
        "sha256": digest,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
