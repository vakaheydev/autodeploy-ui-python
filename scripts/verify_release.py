"""Install a release bundle and verify the installed server end to end."""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launcher.installer import ReleaseInstaller  # noqa: E402
from launcher.paths import InstallPaths  # noqa: E402


def free_port() -> int:
    with socket.socket() as value:
        value.bind(("127.0.0.1", 0))
        return int(value.getsockname()[1])


def request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: object | None = None,
) -> tuple[int, dict[str, str], bytes]:
    encoded = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    call = urllib.request.Request(
        base + path,
        data=encoded,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(call, timeout=10) as response:
        return (
            response.status,
            {key.casefold(): value for key, value in response.headers.items()},
            response.read(2 * 1024 * 1024),
        )


def wait_for_health(base: str, process: subprocess.Popen[str]) -> dict[str, object]:
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Installed server stopped with {process.returncode}:\n{output}")
        try:
            status, _headers, content = request(base, "/api/v1/health")
            payload = json.loads(content)
            if status == 200 and payload.get("service") == "gravitee-autodeploy-web":
                return payload
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.15)
    raise TimeoutError(f"Installed server did not become healthy: {last_error}")


def verify(bundle: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="autodeploy-release-check-") as directory:
        root = Path(directory)
        paths = InstallPaths.create(root)
        installer = ReleaseInstaller(paths)
        version = installer.install_bundle(bundle)
        python = installer.current_python()
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        environment = os.environ.copy()
        environment.update({
            "AUTODEPLOY_HOST": "127.0.0.1",
            "AUTODEPLOY_PORT": str(port),
            "AUTODEPLOY_OPEN_BROWSER": "false",
            "AUTODEPLOY_OPENCODE_AUTO_CONNECT": "false",
            "AUTODEPLOY_DATA_DIR": str(paths.data),
            "AUTODEPLOY_ENV_FILE": str(paths.env_file),
            "AUTODEPLOY_LOG_DIR": str(paths.logs),
            "PYTHONUNBUFFERED": "1",
        })
        process = subprocess.Popen(
            [str(python), "-m", "webapp"],
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            health = wait_for_health(base, process)
            status, headers, html = request(base, "/forms/api.create")
            assert status == 200 and "text/html" in headers.get("content-type", "")
            assert b'<div id="root"></div>' in html
            asset = re.search(rb'(?:src|href)="(/assets/[^"]+)"', html)
            assert asset, "Bundled index.html does not reference an asset"
            asset_status, _asset_headers, asset_body = request(
                base, asset.group(1).decode("ascii")
            )
            assert asset_status == 200 and asset_body

            status, _headers, content = request(
                base, "/api/v1/forms/api.create?environment=test_int"
            )
            form = json.loads(content)
            assert status == 200 and form["id"] == "api.create"
            status, _headers, content = request(
                base,
                "/api/v1/forms/api.create/preview",
                method="POST",
                body={
                    "environment": "test_int",
                    "form_version": form["version"],
                    "values": {
                        "name": "Release Check API",
                        "owner": "Release Engineering",
                        "category": "internal",
                        "context_path": "/release/check",
                        "endpoint_type": "rest",
                    },
                },
            )
            preview = json.loads(content)
            assert status == 200 and preview["valid"] is True
            assert preview["payload"]["contextPath"] == "/release/check"
            assert (paths.logs / "autodeploy.log").is_file()
            return {
                "version": version,
                "health": health,
                "installed_python": str(python),
                "spa_bytes": len(html),
                "asset_bytes": len(asset_body),
            }
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    result = verify(args.bundle.expanduser().resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
