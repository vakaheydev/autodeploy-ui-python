"""Authenticate against a standalone CLI with its printed random password."""
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.env_manager import EnvManager
from opencode_integration.client import OpenCodeError
from opencode_integration.manager import OpenCodeManager
from webapp.api import router


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AUTODEPLOY_TEST_OPENCODE"),
    reason="set AUTODEPLOY_TEST_OPENCODE to test real 2.0.32",
)
@pytest.mark.parametrize("saved_username", ["opencode", "legacy-user", ""])
def test_external_generated_password_login(tmp_path, saved_username):
    environment = os.environ.copy()
    for key in ("OPENCODE_PASSWORD", "OPENCODE_SERVER_PASSWORD",
                "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT"):
        environment.pop(key, None)
    for key, folder in (("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"),
                        ("OPENCODE_CONFIG_DIR", "config")):
        environment[key] = str(tmp_path / folder)
    environment["OPENCODE_DISABLE_MODELS_FETCH"] = "true"
    output = queue.Queue()
    process = subprocess.Popen(
        [os.environ["AUTODEPLOY_TEST_OPENCODE"], "serve", "--hostname", "127.0.0.1", "--port", "0"],
        cwd=tmp_path, env=environment, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    manager = None

    def read_output():
        for line in process.stdout:
            # Never print the credential or arbitrary server output in failures.
            if line.startswith("server listening on ") or line.startswith("server password "):
                output.put(line.strip())

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        address = password = ""
        deadline = time.monotonic() + 40
        while not address or not password:
            line = output.get(timeout=max(0.1, deadline - time.monotonic()))
            if line.startswith("server listening on "):
                address = line.removeprefix("server listening on ")
            elif line.startswith("server password "):
                password = line.removeprefix("server password ")
        env = EnvManager(tmp_path / ".env")
        env.save({"OPENCODE_SERVER_URL": address, "OPENCODE_SERVER_USERNAME": saved_username})
        manager = OpenCodeManager(
            Path(__file__).parents[1], server_url=address, username=saved_username,
            runtime_dir=tmp_path / "autodeploy-runtime", connect_timeout=15,
        )
        with pytest.raises(OpenCodeError):
            manager.connect()
        assert manager.status.auth_required
        app = FastAPI()
        app.state.container = SimpleNamespace(env_manager=env, opencode_manager=manager)
        app.include_router(router)
        with TestClient(app) as client:
            result = client.post("/api/v1/opencode/authenticate", json={"password": password})
            assert result.status_code == 200
            state = result.json()
            assert state["state"] == "ready", state["message"]
            assert state["auth_required"] is False
            assert state["version"] == "2.0.32"
            assert state["ownership"] == "external"
            assert process.poll() is None
            assert password not in result.text
    finally:
        if manager:
            manager.stop()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        reader.join(timeout=2)
        process.stdout.close()
