"""Opt-in native CLI test with a local fake provider; no paid/model network calls.

AUTODEPLOY_TEST_OPENCODE=/path/to/opencode pytest tests/test_opencode_v2_live.py
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from opencode_integration.manager import OpenCodeManager


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("AUTODEPLOY_TEST_OPENCODE"), reason="set AUTODEPLOY_TEST_OPENCODE to test real 2.0.32")
@pytest.mark.parametrize("mcp_policy", ["none", "allow", "ask"])
def test_real_v2_cli_turn_and_restoration(tmp_path, monkeypatch, mcp_policy):
    requests = []
    tool_calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/mcp"):
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                method = body["method"]
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "local-test", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": name, "description": name, "inputSchema": {
                        "type": "object", "properties": {}, "additionalProperties": False,
                    }} for name in ("search", "delete")]}
                elif method == "tools/call":
                    tool_calls.append(body["params"]["name"])
                    result = {"content": [{"type": "text", "text": "LOCAL_MCP_EVIDENCE"}]}
                else:
                    result = {}
                raw = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            requests.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            deltas = [({"role": "assistant", "content": '{"ok":true}'}, None), ({}, "stop")]
            names = [t["function"]["name"] for t in body.get("tools", [])]
            if "test_repo_search" in names and not any(m.get("role") == "tool" for m in body["messages"]):
                deltas = [({"role": "assistant", "tool_calls": [{"index": 0, "id": "call_search", "type": "function",
                           "function": {"name": "test_repo_search", "arguments": "{}"}}]}, None), ({}, "tool_calls")]
            for delta, finish in deltas:
                chunk = {"id": "chatcmpl-local", "object": "chat.completion.chunk", "created": 1,
                         "model": "test-model", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for variable, folder in [("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"),
                             ("OPENCODE_CONFIG_DIR", "config")]:
        monkeypatch.setenv(variable, str(tmp_path / folder))
    monkeypatch.setenv("OPENCODE_DISABLE_MODELS_FETCH", "true")
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "opencode.json").write_text(json.dumps({
        "model": "local/test-model",
        "mcp": {"servers": {"test_repo": {"type": "remote", "oauth": False,
                "url": f"http://127.0.0.1:{server.server_port}/mcp"}}} if mcp_policy != "none" else {},
        "providers": {"local": {
            "name": "Local test", "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": f"http://127.0.0.1:{server.server_port}/v1", "apiKey": "local-test"},
            "models": {"test-model": {"name": "Test model", "variants": [{"id": "none"}],
                                       "limit": {"context": 32000, "output": 2000}}},
        }},
    }))
    manager = OpenCodeManager(Path(__file__).parents[1], command=os.environ["AUTODEPLOY_TEST_OPENCODE"],
                              runtime_dir=runtime, startup_timeout=40, request_timeout=20)
    try:
        client = manager.create()
        assert client.health().version == "2.0.32"
        catalog = client.configured_model_catalog(agent_name="form-search")
        assert catalog.default.provider_id == "local"
        session = client.create_session("V2 integration test", agent="form-search", provider_id="local",
                                         model_id="test-model", variant="none",
                                         mcp_names=["test_repo"] if mcp_policy != "none" else [],
                                         mcp_tool_allowlist={"test_repo": ["search"]} if mcp_policy == "allow" else {},
                                         mcp_tool_asklist={"test_repo": ["search"]} if mcp_policy == "ask" else {})
        assert client.get_session(session)["permissions"][0] == {"action": "*", "resource": "*", "effect": "deny"}
        client.add_session_context(session_id=session, prompt="CATALOG_ONLY_ONCE", agent="form-search",
                                   provider_id="local", model_id="test-model", variant="none")
        assert not requests
        permissions = []

        def on_event(event):
            if event["type"] == "permission.asked":
                permissions.append(event)
                client.respond_permission(session, event["properties"]["id"], "once")

        result = client.send_structured_message(
            session_id=session, prompt="test", system="TRUSTED_TEST_INSTRUCTION", agent="form-search",
            provider_id="local", model_id="test-model", variant="none",
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            on_event=on_event,
        )
        assert result == {"ok": True}
        assert any("CATALOG_ONLY_ONCE" in json.dumps(r) for r in requests)
        assert any("TRUSTED_TEST_INSTRUCTION" in json.dumps(r) for r in requests)
        if mcp_policy != "none":
            assert tool_calls == ["search"], {
                "tools": [[t["function"]["name"] for t in r.get("tools", [])] for r in requests],
                "permissions": permissions,
                "history": client.list_session_messages(session),
            }
            assert any("LOCAL_MCP_EVIDENCE" in json.dumps(r) for r in requests)
            assert bool(permissions) == (mcp_policy == "ask")
            for request in requests:
                names = [t["function"]["name"] for t in request.get("tools", [])]
                assert "test_repo_delete" not in names
                assert "execute" not in names
        history = client.list_session_messages(session)
        assert history[-1]["parts"][0]["text"] == '{"ok":true}'
        client.update_session_title(session, "Renamed")
        assert client.get_session(session)["title"] == "Renamed"
        client.abort_session(session)
        client.delete_session(session)
        assert not client.list_sessions()
    finally:
        manager.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
