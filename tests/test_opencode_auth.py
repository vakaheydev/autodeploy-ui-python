"""Authentication recovery uses typed HTTP errors and never restarts a server."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.env_manager import EnvManager
from opencode_integration.client import OpenCodeError
from opencode_integration.manager import OpenCodeManager
from webapp.api import router


@pytest.fixture(params=["1.18.18", "2.0.32"])
def protected_server(request):
    state = SimpleNamespace(password="test-password", username="opencode", version=request.param, offline=False)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            expected = "Basic " + base64.b64encode(
                f"{state.username}:{state.password}".encode()
            ).decode()
            code, body = 200, {}
            if state.offline:
                code = 503
            elif self.headers.get("Authorization") != expected:
                code = 401
                body = {"password": state.password}  # Must never reach UI/logs.
            elif self.path == "/api/info":
                if request.param.startswith("1"):
                    code = 404
                else:
                    body = {"version": request.param}
            elif self.path == "/global/health":
                body = {"healthy": True, "version": request.param}
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.address = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def manager(tmp_path, protected_server):
    value = OpenCodeManager(
        Path(__file__).parents[1], runtime_dir=tmp_path / "runtime",
        server_url=protected_server.address, connect_timeout=1,
    )
    value._require_agents = Mock()
    yield value
    value.stop()


def test_initial_401_retry_and_active_connection_expiry(manager, protected_server):
    with pytest.raises(OpenCodeError):
        manager.connect()
    assert manager.status.auth_required
    assert protected_server.password not in manager.status.message
    manager.configure(password=protected_server.password)
    assert manager.check_status(refresh_credentials=True).state == "ready"
    assert not manager.status.auth_required
    old = manager.client
    protected_server.password = "rotated-password"
    with pytest.raises(OpenCodeError):
        old.health()
    assert manager.status.auth_required
    assert manager.client is None
    protected_server.offline = True
    with pytest.raises(OpenCodeError):
        manager.check_status()
    assert manager.status.auth_required  # An outage does not prove login succeeded.
    protected_server.offline = False
    manager.configure(password=protected_server.password)
    manager.check_status(refresh_credentials=True)
    with pytest.raises(OpenCodeError):
        old.health()
    assert not manager.status.auth_required  # Ignore an obsolete client's 401.
    assert manager.is_ready


def test_saved_legacy_username_is_used_only_for_v1(manager, protected_server):
    if protected_server.version.startswith("1."):
        protected_server.username = "legacy-user"
    manager.configure(username="legacy-user", password=protected_server.password)
    client = manager.connect()
    assert manager.is_ready
    assert client.username == protected_server.username
    assert not manager.status.auth_required
    # Every later operation must use the selected identity, too.
    assert client.health().version == protected_server.version


def test_password_api_is_write_only_and_preserves_owned_server(manager, protected_server, tmp_path):
    manager.configure(password=protected_server.password)
    manager.connect()
    process = Mock(pid=1234)
    process.poll.return_value = None
    manager._process = process
    manager._ownership = "owned"
    terminate = manager._terminate_process = Mock()
    app = FastAPI()
    env = EnvManager(tmp_path / ".env")
    app.state.container = SimpleNamespace(opencode_manager=manager, env_manager=env)
    app.include_router(router)
    with TestClient(app) as client:
        failed = client.post("/api/v1/opencode/authenticate", json={"password": "wrong-password"})
        assert failed.json()["auth_required"] is True
        assert "wrong-password" not in failed.text
        result = client.post("/api/v1/opencode/authenticate", json={"password": protected_server.password})
        assert result.status_code == 200
        assert result.json()["state"] == "ready"
        assert result.json()["auth_required"] is False
        assert result.json()["address"] == protected_server.address
        assert result.json()["ownership"] == "owned"
        assert protected_server.password not in result.text
        assert protected_server.password not in client.get("/api/v1/settings").text
        assert env.get("OPENCODE_SERVER_PASSWORD") == protected_server.password
        terminate.assert_not_called()
        process.terminate.assert_not_called()
