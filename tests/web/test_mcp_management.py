import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.env_manager import EnvManager
from opencode_integration.client import build_session_permissions
from opencode_integration.copilot import UnifiedCopilot
from opencode_integration.mcp_discovery import discover_mcp_tools
from webapp.mcp_management import MCPManagement


def manager(tmp_path, monkeypatch):
    client = Mock(directory=str(tmp_path))
    client.mcp_configurations.return_value = {"docs": {"type": "local", "command": ["example"],
                                                        "environment": {"PASSWORD": "not-public"}}}
    client.list_mcp_servers.return_value = {"docs": {"status": "connected"}}
    client.clear_saved_mcp_permissions.return_value = True
    container = SimpleNamespace(
        settings=SimpleNamespace(data_dir=tmp_path, mcp_enabled=False),
        env_manager=EnvManager(tmp_path / ".env"),
        opencode_manager=SimpleNamespace(client=client),
    )
    container.env_manager.save({"OPENCODE_ALLOWED_MCP": "docs"})
    discover = Mock(return_value=[{"name": "read_page", "description": "Read page", "input_schema": {}},
                                 {"name": "update_page", "description": "Update page", "input_schema": {}}])
    monkeypatch.setattr("webapp.mcp_management.discover_mcp_tools", discover)
    return MCPManagement(container), client, discover


def test_catalog_exact_policies_persist_and_do_not_leak_configuration(tmp_path, monkeypatch):
    store, client, discover = manager(tmp_path, monkeypatch)
    catalog = store.catalog("docs")
    assert [tool["policy"] for tool in catalog["tools"]] == ["ask", "deny"]
    assert "not-public" not in json.dumps(catalog)
    store.update("docs", "update_page", "allow")
    store.update("docs", "read_page", "deny")
    assert MCPManagement(store.container).session_configuration()["rules"] == [
        {"permission": "docs_update_page", "pattern": "*", "action": "allow"},
        {"permission": "docs_read_page", "pattern": "*", "action": "deny"},
    ]
    store.update("docs", "update_page", "ask")
    client.clear_saved_mcp_permissions.assert_called_once_with("docs", "update_page")
    assert discover.call_count == 1
    with pytest.raises(ValueError):
        store.update("docs", "*", "allow")
    with pytest.raises(ValueError):
        store.update("docs", "missing", "allow")


def test_restart_invalidates_catalog_and_only_targets_selected_server(tmp_path, monkeypatch):
    store, client, discover = manager(tmp_path, monkeypatch)
    store.catalog("docs")
    store.restart("docs")
    store.catalog("docs")
    client.restart_mcp.assert_called_once_with("docs")
    assert discover.call_count == 2
    with pytest.raises(ValueError):
        store.restart("unknown")


def test_mcp_http_catalog_policy_and_restart(tmp_path, monkeypatch):
    from webapp.api import router
    store, client, _ = manager(tmp_path, monkeypatch)
    store.container.mcp_management = store
    app = FastAPI()
    app.state.container = store.container
    app.include_router(router)
    with TestClient(app) as http:
        result = http.get("/api/v1/opencode/mcp/docs/tools")
        assert result.status_code == 200
        assert result.json()["tools"][0]["name"] == "read_page"
        result = http.post("/api/v1/opencode/mcp/docs/tools/read_page/policy", json={"policy": "allow"})
        assert result.json() == {"saved": True, "applies": "next_turn"}
        assert http.post("/api/v1/opencode/mcp/docs/tools/read_page/policy", json={"policy": "unknown"}).status_code == 422
        assert http.post("/api/v1/opencode/mcp/docs/restart", json={}).json() == {"restarted": True}
    client.restart_mcp.assert_called_once_with("docs")


def test_catalog_failure_keeps_saved_policies_and_hides_credentials(tmp_path, monkeypatch):
    store, _, discover = manager(tmp_path, monkeypatch)
    store.update("docs", "read_page", "deny")
    discover.side_effect = RuntimeError("PASSWORD=not-public")
    with pytest.raises(RuntimeError) as error:
        store.catalog("docs", refresh=True)
    assert "not-public" not in str(error.value)
    assert store.session_configuration()["rules"][0]["action"] == "deny"


def test_restored_session_connects_selected_mcp_and_refreshes_rules_next_turn(tmp_path, monkeypatch):
    store, client, _ = manager(tmp_path, monkeypatch)
    client.timeout = 10
    store.update("docs", "read_page", "deny")
    copilot = UnifiedCopilot(client, Mock(), Mock(), forms=[], workflow_id="workflow",
                             mcp_configuration=store.session_configuration)
    copilot._session_id = "ses_restored"
    copilot._session_context_initialized = True
    copilot._ensure_session(lambda _: None)
    client.prepare_mcp.assert_called_with(("docs",))
    rules = client.update_session_permissions.call_args.args[1]
    assert rules[-1] == {"permission": "docs_read_page", "pattern": "*", "action": "deny"}
    assert rules[:2] == build_session_permissions([])[:2]
    assert copilot._session_context_initialized is False
    store.update("docs", "read_page", "allow")
    copilot._ensure_session(lambda _: None)
    assert client.update_session_permissions.call_args.args[1][-1]["action"] == "allow"
    client.create_session.assert_not_called()


def test_stdio_catalog_uses_initialize_and_paginated_tools_list_only(tmp_path):
    program = tmp_path / "catalog_server.py"
    calls = tmp_path / "calls.jsonl"
    program.write_text('''import json,sys
for line in sys.stdin:
    message=json.loads(line)
    with open(sys.argv[1],"a") as output: output.write(json.dumps(message)+"\\n")
    if "id" not in message: continue
    method=message["method"]
    if method=="initialize":
        result={"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"test","version":"1"}}
    elif method=="tools/list":
        second=message.get("params",{}).get("cursor")=="next"
        result={"tools":[{"name":"read_second" if second else "read_first","inputSchema":{"type":"object"}}]}
        if not second: result["nextCursor"]="next"
    else: raise RuntimeError("Unexpected call")
    print(json.dumps({"jsonrpc":"2.0","id":message["id"],"result":result}),flush=True)
''')
    tools = discover_mcp_tools({"type": "local", "command": [sys.executable, str(program), str(calls)]}, str(tmp_path))
    assert [tool["name"] for tool in tools] == ["read_first", "read_second"]
    methods = [json.loads(line)["method"] for line in calls.read_text().splitlines()]
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/list"]
