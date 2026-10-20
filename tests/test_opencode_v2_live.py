"""Opt-in native CLI test with a local fake provider; no paid/model network calls.

AUTODEPLOY_TEST_OPENCODE=/path/to/opencode pytest tests/test_opencode_v2_live.py
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from opencode_integration.manager import OpenCodeManager
from opencode_integration.client import OpenCodeCancelled
from opencode_integration.client import build_session_permissions
from opencode_integration.mcp_discovery import discover_mcp_tools
from opencode_integration.copilot import UnifiedCopilot
from unittest.mock import Mock


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("AUTODEPLOY_TEST_OPENCODE"), reason="set AUTODEPLOY_TEST_OPENCODE to test real 2.0.32")
@pytest.mark.parametrize("mcp_policy", ["none", "allow", "ask"])
def test_real_v2_cli_turn_and_restoration(tmp_path, monkeypatch, mcp_policy):
    requests = []
    tool_calls = []
    queue_started = threading.Event()
    queue_release = threading.Event()

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
            last_user = json.dumps([m for m in body.get("messages", []) if m.get("role") == "user"][-1:])
            queue_reply = ""
            if "QUEUE_FIRST" in last_user:
                queue_started.set()
                queue_release.wait(15)
                queue_reply = "FIRST_REPLY"
            elif "QUEUE_SECOND" in last_user:
                queue_reply = "SECOND_REPLY"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            deltas = [({"role": "assistant", "content": '{"ok":true}'}, None), ({}, "stop")]
            if queue_reply:
                deltas = [({"role": "assistant", "content": queue_reply}, None), ({}, "stop")]
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
        assert client.list_message_queue(session) == []  # Context is native inbox data, not a follow-up.
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
        if mcp_policy == "ask":
            native = client._v2
            copilot = UnifiedCopilot(client, Mock(), Mock(), forms=[], workflow_id="test")
            copilot._session_id = session
            for decision in ("once", "reject", "always"):
                payload = {"action": "test_repo_search", "resources": [f"example/{decision}"],
                           "save": [f"example/{decision}"]}
                pending = native._wire("POST", f"/api/session/{session}/permission", payload)["data"]
                assert pending["effect"] == "ask"
                assert copilot.approve_permission(pending["id"], allow=decision != "reject",
                                                  always=decision == "always")
                assert not any(row["id"] == pending["id"] for row in client.list_pending_permissions())
                assert copilot.approve_permission(pending["id"], allow=True) is False
            saved_session = client.create_session(agent="form-search", mcp_names=["test_repo"],
                                                   mcp_tool_asklist={"test_repo": ["search"]})
            saved = native._wire("POST", f"/api/session/{saved_session}/permission", payload)["data"]
            assert saved["effect"] == "allow"  # V2 saves this resource for the project, across sessions.
            different = native._wire("POST", f"/api/session/{saved_session}/permission", {
                **payload, "resources": ["example/another"], "save": ["example/another"],
            })["data"]
            assert different["effect"] == "ask"
            client.respond_permission(saved_session, different["id"], "reject")
            assert client.clear_saved_mcp_permissions("test_repo", "search") is True
            revoked = native._wire("POST", f"/api/session/{saved_session}/permission", payload)["data"]
            assert revoked["effect"] == "ask"
            client.respond_permission(saved_session, revoked["id"], "reject")
            client.delete_session(saved_session)
        if mcp_policy == "allow":
            config = client.mcp_configurations()["test_repo"]
            discovered = discover_mcp_tools(config, client.directory)
            assert {tool["name"] for tool in discovered} == {"search", "delete"}
            assert tool_calls == ["search"]  # Catalog discovery never calls tools.
            client.restart_mcp("test_repo")
            client.prepare_mcp(["test_repo"])
            client.update_session_permissions(session, build_session_permissions(
                ["test_repo"], {"test_repo": ["search"]},
            ))
            assert {"action": "test_repo_search", "resource": "*", "effect": "allow"} in client.get_session(session)["permissions"]
            assert client.list_mcp_servers()["test_repo"]["status"] == "connected"
        history = client.list_session_messages(session)
        assert history[-1]["parts"][0]["text"] == '{"ok":true}'
        client.update_session_title(session, "Renamed")
        assert client.get_session(session)["title"] == "Renamed"
        if mcp_policy == "none":
            # Observe the real V2 inbox while the fake provider holds the first
            # response. OpenCode itself must deliver the follow-up, with no
            # Python dispatcher calling send_chat_message a second time.
            queued_session = client.create_session(agent="autodeploy-copilot", provider_id="local",
                                                    model_id="test-model", variant="none")
            events = []
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    client.send_chat_message, session_id=queued_session, prompt="QUEUE_FIRST",
                    agent="autodeploy-copilot", provider_id="local", model_id="test-model",
                    variant="none", on_event=events.append,
                )
                try:
                    assert queue_started.wait(10)
                    second = client.enqueue_message(queued_session, "QUEUE_SECOND",
                                                    metadata={"source": "autodeploy-queue", "message": "Second"},
                                                    require_active=True)
                    third = client.enqueue_message(queued_session, "QUEUE_REMOVE", require_active=True)
                    assert [row["id"] for row in client.list_message_queue(queued_session)] == [second["id"], third["id"]]
                    client.cancel_queued_message(queued_session, third["id"])
                    assert [row["id"] for row in client.list_message_queue(queued_session)] == [second["id"]]
                finally:
                    queue_release.set()
                assert future.result(timeout=20).text == "SECOND_REPLY"
            assert client.list_message_queue(queued_session) == []
            delivered = [event for event in events if event["type"] == "client.queue.user"]
            assert [event["properties"]["id"] for event in delivered] == [second["id"]]
            replies = [event for event in events if event["type"] == "client.queue.reply"]
            assert replies[0]["properties"]["messages"][-1]["parts"][0]["text"] == "FIRST_REPLY"
            client.delete_session(queued_session)
            queue_started.clear()
            queue_release.clear()
            stopped_session = client.create_session(agent="autodeploy-copilot", provider_id="local",
                                                     model_id="test-model", variant="none")
            cancel = threading.Event()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    client.send_chat_message, session_id=stopped_session, prompt="QUEUE_FIRST",
                    agent="autodeploy-copilot", provider_id="local", model_id="test-model",
                    variant="none", cancel_event=cancel, on_event=lambda _event: None,
                )
                try:
                    assert queue_started.wait(10)
                    pending = client.enqueue_message(stopped_session, "QUEUE_SECOND", require_active=True)
                    cancel.set()
                    with pytest.raises(OpenCodeCancelled):
                        future.result(timeout=10)
                    assert [row["id"] for row in client.list_message_queue(stopped_session)] == [pending["id"]]
                finally:
                    queue_release.set()
            resumed = client.resume_message_queue(stopped_session, on_event=lambda _event: None)
            assert resumed["parts"][0]["text"] == "SECOND_REPLY"
            history = client.list_session_messages(stopped_session)
            assert sum(row["info"].get("id") == pending["id"] for row in history) == 1
            client.delete_session(stopped_session)
        client.abort_session(session)
        client.delete_session(session)
        assert not client.list_sessions()
    finally:
        manager.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
