from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from launcher.envfile import read_env, update_env
from launcher.installer import ReleaseInstaller, UpdateLock
from launcher.manifest import ReleaseManifest, version_key
from launcher.paths import InstallPaths
from launcher.provider import TfsUpdateProvider
from scripts import build_release


def test_manifest_semver_and_strict_contract() -> None:
    manifest = ReleaseManifest.parse({
        "schema_version": 1,
        "version": "1.4.0",
        "artifact_url": "https://tfs.example/release.zip",
        "sha256": "a" * 64,
        "changelog": "Release",
        "minimum_launcher_version": "1.0.0",
    })
    assert manifest.newer_than("1.3.9")
    assert version_key("2.0.0") > version_key("2.0.0-rc.1")
    with pytest.raises(ValueError, match="Неизвестные"):
        ReleaseManifest.parse({**manifest.__dict__, "unexpected": True})


def test_env_update_is_atomic_and_preserves_server_settings(tmp_path: Path) -> None:
    path = tmp_path / "config" / ".env"
    update_env(path, {"GRAVITEE_TOKEN_TEST_INT": "secret", "TFS_TOKEN": "old"})
    update_env(path, {"TFS_TOKEN": "new"})
    assert read_env(path) == {
        "GRAVITEE_TOKEN_TEST_INT": "secret",
        "TFS_TOKEN": "new",
    }
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_zip_slip_and_symlinks_are_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "bad")
        archive.writestr("release.json", "{}")
    installer = ReleaseInstaller(InstallPaths.create(tmp_path / "install"))
    with pytest.raises(ValueError, match="Небезопасный путь"):
        installer.install_bundle(archive_path)


def test_installer_rechecks_manifest_digest_before_extraction(tmp_path: Path) -> None:
    archive_path = tmp_path / "release.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("release.json", json.dumps({
            "schema_version": 1,
            "version": "1.0.0",
        }))
    manifest = ReleaseManifest(
        version="1.0.0",
        artifact_url="https://tfs.example/release.zip",
        sha256="0" * 64,
        changelog="test",
        size=archive_path.stat().st_size,
    )
    installer = ReleaseInstaller(InstallPaths.create(tmp_path / "install"))

    with pytest.raises(ValueError, match="SHA-256 release bundle"):
        installer.install_bundle(archive_path, expected=manifest)


def test_update_lock_prevents_concurrent_install(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    with UpdateLock(path):
        with pytest.raises(RuntimeError, match="уже выполняется"):
            with UpdateLock(path):
                pass
    assert not path.exists()


def test_release_runtime_compatibility_is_checked() -> None:
    current = f"{sys.version_info.major}{sys.version_info.minor}"
    ReleaseInstaller._check_runtime({
        "python_requires": ">=3.10,<3.14",
        "python_versions": [current],
        "target_platform": "windows_amd64" if os.name == "nt" else "linux_x86_64",
    })
    with pytest.raises(RuntimeError, match="не содержит wheels"):
        ReleaseInstaller._check_runtime({
            "python_requires": ">=3.10,<3.14",
            "python_versions": ["399"],
        })
    with pytest.raises(RuntimeError, match="собран для"):
        ReleaseInstaller._check_runtime({
            "target_platform": "linux_x86_64" if os.name == "nt" else "win_amd64",
        })


def test_provider_downloads_and_verifies_sha256(tmp_path: Path) -> None:
    artifact = b"release archive bytes"
    digest = hashlib.sha256(artifact).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/manifest":
                body = json.dumps({
                    "schema_version": 1,
                    "version": "1.2.3",
                    "artifact_url": f"http://127.0.0.1:{self.server.server_port}/release.zip",
                    "sha256": digest,
                    "size": len(artifact),
                    "changelog": "Test",
                    "minimum_launcher_version": "1.0.0",
                }).encode()
            else:
                body = artifact
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = TfsUpdateProvider(f"http://127.0.0.1:{server.server_port}/manifest", "token")
        manifest = provider.fetch_manifest()
        destination = provider.download(manifest, tmp_path / "download.zip")
        assert destination.read_bytes() == artifact
    finally:
        server.shutdown()
        server.server_close()


def test_release_build_removes_stale_setuptools_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    (tmp_path / "build" / "lib" / "webapp" / "static").mkdir(parents=True)
    (tmp_path / "build" / "lib" / "webapp" / "static" / "old.js").write_text("old")
    (tmp_path / "build" / "bdist.test").mkdir()
    (tmp_path / "build" / "release").mkdir()
    (tmp_path / "gravitee_autodeploy.egg-info").mkdir()

    build_release.clean_python_build_cache()

    assert not (tmp_path / "build" / "lib").exists()
    assert not (tmp_path / "build" / "bdist.test").exists()
    assert not (tmp_path / "gravitee_autodeploy.egg-info").exists()
    assert (tmp_path / "build" / "release").is_dir()
