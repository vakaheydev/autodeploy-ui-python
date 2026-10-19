"""Automatic adapter selection must never retry mutations across protocols."""
from unittest.mock import Mock, patch
from pathlib import Path
import json

import pytest

from opencode_integration.client import (
    OpenCodeError, OpenCodeHealth, OpenCodeHttpError, OpenCodeProtocolError,
)
from opencode_integration.connection import OpenCodeConnection
from opencode_integration.manager import OpenCodeManager


@pytest.mark.parametrize("missing", [OpenCodeHttpError(404, "missing"), OpenCodeHttpError(405, "missing"),
                                      OpenCodeProtocolError("HTML")])
def test_v1_selected_after_missing_v2_api(missing):
    connection = OpenCodeConnection("http://127.0.0.1:4096")
    connection._v2 = Mock()
    connection._v2.health.side_effect = missing
    connection._v1 = Mock(timeout=10)
    connection._v1.health.return_value = OpenCodeHealth(True, "1.18.18")
    connection._v1.create_session.return_value = "ses_legacy"
    assert connection.health().version == "1.18.18"
    assert connection.create_session("test") == "ses_legacy"
    connection.health()
    assert connection._v2.health.call_count == 1
    connection._v2.create_session.assert_not_called()


def test_v2_selected_lazily_and_cached():
    connection = OpenCodeConnection("http://127.0.0.1:4096")
    connection._v2 = Mock()
    connection._v2.health.return_value = OpenCodeHealth(True, "2.0.32")
    connection._v2.create_session.return_value = "ses_native"
    connection._v1 = Mock(timeout=10)
    assert connection.create_session("test") == "ses_native"
    connection.delete_session("ses_native")
    connection._v2.health.assert_called_once()
    connection._v1.health.assert_not_called()
    connection._v1.create_session.assert_not_called()


@pytest.mark.parametrize("error", [OpenCodeHttpError(401, "auth"), OpenCodeHttpError(500, "failure"),
                                    OpenCodeError("offline"), OpenCodeError("unsupported version")])
def test_auth_network_and_server_errors_do_not_fall_back(error):
    connection = OpenCodeConnection("http://127.0.0.1:4096")
    connection._v2 = Mock()
    connection._v2.health.side_effect = error
    connection._v1 = Mock(timeout=10)
    with pytest.raises(OpenCodeError):
        connection.health()
    connection._v1.health.assert_not_called()
    assert connection._adapter is None


def test_mutation_error_never_switches_adapter():
    connection = OpenCodeConnection("http://127.0.0.1:4096")
    connection._v2 = Mock()
    connection._v2.health.return_value = OpenCodeHealth(True, "2.0.32")
    connection._v2.create_session.side_effect = OpenCodeHttpError(404, "missing agent")
    connection._v1 = Mock(timeout=10)
    with pytest.raises(OpenCodeHttpError):
        connection.create_session()
    connection._v1.create_session.assert_not_called()


def test_timeout_update_reaches_both_adapters():
    connection = OpenCodeConnection("http://127.0.0.1:4096")
    connection.timeout = 15
    assert connection._v1.timeout == connection._v2.timeout == 15


@pytest.mark.parametrize("version", ["1.18.18", "2.0.32"])
def test_runtime_config_can_switch_versions_without_stale_managed_entry(tmp_path, version):
    manager = OpenCodeManager(Path(__file__).parents[1], runtime_dir=tmp_path,
                              mcp_url="http://127.0.0.1:8765/api/mcp")
    manager._prepare_runtime(version="2.0.32" if version.startswith("1") else "1.18.18")
    manager._prepare_runtime(version=version)
    mcp = json.loads((tmp_path / "opencode.json").read_text())["mcp"]
    if version.startswith("1"):
        assert mcp == {"autodeploy": {"type": "remote", "url": manager.mcp_url, "enabled": True}}
    else:
        assert "autodeploy" not in mcp
        assert mcp["servers"]["autodeploy"]["codemode"] is False


@pytest.mark.parametrize("password", ["", "configured-secret"])
def test_v1_launch_preserves_optional_auth_and_username(tmp_path, monkeypatch, password):
    monkeypatch.setenv("OPENCODE_PASSWORD", "unrelated")
    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "unrelated")
    manager = OpenCodeManager(Path(__file__).parents[1], runtime_dir=tmp_path, password=password, username="legacy-user")
    manager._launch_version = "1.18.18"
    with patch("opencode_integration.manager.subprocess.Popen") as popen, patch.object(manager, "_start_stream_loggers"):
        manager._spawn("opencode", 4097)
    env = popen.call_args.kwargs["env"]
    assert "OPENCODE_PASSWORD" not in env
    if password:
        assert env["OPENCODE_SERVER_PASSWORD"] == password
        assert env["OPENCODE_SERVER_USERNAME"] == "legacy-user"
    else:
        assert "OPENCODE_SERVER_PASSWORD" not in env
        assert "OPENCODE_SERVER_USERNAME" not in env
    assert manager._owned_password == password
