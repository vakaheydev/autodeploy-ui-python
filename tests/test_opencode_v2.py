"""Native 2.0.32 contracts: envelopes, durable turns and fail-closed rules."""
import base64
import copy
import json
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from opencode_integration.client import OpenCodeCancelled, OpenCodeError, OpenCodeAgentMissingError
from opencode_integration.client_v2 import OpenCodeV2Client, _message
from opencode_integration.manager import OpenCodeManager


class Client(OpenCodeV2Client):
    def __init__(self, replies=()):
        super().__init__("http://127.0.0.1:4096", timeout=1, directory="/tmp/runtime")
        self.calls = []
        self.replies = iter(replies)

    def _wire(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path, payload))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return copy.deepcopy(reply)


def page(*items, next_cursor=None):
    return {"data": list(items), "cursor": {"next": next_cursor} if next_cursor else {}}


def assistant(text="done", **extra):
    return {"id": "msg_answer", "type": "assistant", "content": [{"type": "text", "text": text}],
            "time": {"created": 1000, "completed": 2000}, **extra}


PROMPT = {"id": "msg_prompt", "type": "user", "text": "hello"}
IDLE = {"id": "msg_idle", "type": "idle", "outcome": "succeeded"}


def send(client, **kwargs):
    return client.send_chat_message(session_id="ses_test", prompt="hello", agent="form-search", **kwargs)


def test_health_uses_native_info_and_rejects_v1():
    client = Client([{"version": "2.0.32"}, {"version": "1.18.18"}])
    assert client.health().healthy
    with pytest.raises(OpenCodeError):
        client.health()
    assert client.calls[0][:2] == ("GET", "/api/info")


def test_native_rules_location_and_explicit_model():
    config = [{"type": "document", "info": {"mcp": {"servers": {
        "repo": {"type": "remote", "url": "http://127.0.0.1:9999/mcp", "codemode": False},
    }}}}]
    client = Client([config, {"data": {"id": "ses_test"}}])
    client.create_session(agent="autodeploy-copilot", provider_id="local", model_id="model", variant="none",
                          mcp_names=["repo"], mcp_tool_allowlist={"repo": ["search"]},
                          mcp_tool_asklist={"repo": ["git_pull"]})
    method, path, body = client.calls[-1]
    assert (method, path) == ("POST", "/api/session")
    assert "permission" not in body
    assert body["location"] == {"directory": client.directory}
    assert body["model"] == {"providerID": "local", "id": "model", "variant": "none"}
    assert body["permissions"] == [
        {"action": "*", "resource": "*", "effect": "deny"},
        {"action": "StructuredOutput", "resource": "*", "effect": "deny"},
        {"action": "repo_search", "resource": "*", "effect": "allow"},
        {"action": "repo_git_pull", "resource": "*", "effect": "ask"},
    ]


def test_selected_mcp_exposed_directly_without_enabling_execute():
    config = {"type": "remote", "url": "http://127.0.0.1:9999/mcp", "headers": {"x-test": "secret"}}
    client = Client([[{"info": {"mcp": {"servers": {"repo": config}}}}], None,
                     {"data": [{"name": "repo", "status": {"status": "connected"}}]},
                     {"data": {"id": "ses_test"}}])
    client.create_session(mcp_names=["repo"])
    assert client.calls[1] == ("PUT", "/api/experimental/mcp/repo", {"config": {**config, "codemode": False}})
    assert not any(x["action"] == "execute" for x in client.calls[-1][2]["permissions"])


def test_missing_mcp_config_fails_before_session_creation():
    client = Client([[]])
    with pytest.raises(OpenCodeError, match="конфигурации"):
        client.create_session(mcp_names=["repo"])
    assert len(client.calls) == 1


def test_history_follows_cursors_and_removes_reasoning():
    client = Client([page(PROMPT, next_cursor="next/page"), page(assistant(content=[
        {"type": "reasoning", "text": "private"}, {"type": "text", "text": "done"},
    ]), IDLE)])
    result = client.list_session_messages("ses_test")
    assert len(result) == 2
    assert result[-1]["parts"][0]["text"] == "done"
    assert "private" not in json.dumps(result)
    assert "cursor=next%2Fpage" in client.calls[1][1]
    assert "order=" not in client.calls[1][1]


def test_repeated_cursor_fails_instead_of_looping():
    client = Client([page(next_cursor="same"), page(next_cursor="same")])
    with pytest.raises(OpenCodeError, match="cursor"):
        client.list_sessions()


def test_context_is_queued_without_model_execution():
    client = Client([None, None, None, {"data": PROMPT}])
    client.add_session_context(session_id="ses_test", prompt="catalog", system="trusted", agent="form-search",
                               provider_id="local", model_id="m", variant="none")
    assert client.calls[-1] == ("POST", "/api/session/ses_test/prompt", {"text": "catalog", "resume": False})
    assert client.calls[1][2] == {"model": {"providerID": "local", "id": "m", "variant": "none"}}
    assert client.calls[2][2] == {"value": "trusted"}


def test_prompt_waits_for_its_idle_not_old_history():
    client = Client([None, None, {"data": PROMPT}, page(IDLE, assistant("old")),
                     page(IDLE, assistant(), PROMPT)])
    assert send(client).text == "done"
    assert len(client.calls) == 5
    assert client.calls[1][0] == "DELETE"  # Remove stale system instructions.


def test_new_prompt_anchor_can_be_on_an_older_page():
    client = Client([None, None, {"data": PROMPT}, page(IDLE, assistant(), next_cursor="older"), page(PROMPT)])
    assert send(client).text == "done"


@pytest.mark.parametrize("outcome,error", [("interrupted", OpenCodeCancelled), ("failed", OpenCodeError)])
def test_idle_failure_never_returns_partial_success(outcome, error):
    idle = {**IDLE, "outcome": outcome, "error": {"type": "ProviderFailure", "response": {"body": "private"}}}
    client = Client([None, None, {"data": PROMPT}, page(idle, assistant("partial"), PROMPT), None, None])
    with pytest.raises(error) as caught:
        send(client)
    assert "private" not in str(caught.value)
    assert client.calls[-1] == ("POST", "/api/session/ses_test/interrupt", {"resume": False})


def test_cancel_before_admission_does_not_send_prompt():
    cancel = threading.Event()
    cancel.set()
    client = Client()
    with pytest.raises(OpenCodeCancelled):
        send(client, cancel_event=cancel)
    assert not client.calls


def test_cancel_after_admission_interrupts_server():
    cancel = threading.Event()

    class CancelClient(Client):
        def _wire(self, method, path, payload=None, **kwargs):
            result = super()._wire(method, path, payload, **kwargs)
            if path.endswith("/prompt"):
                cancel.set()
            return result

    client = CancelClient([None, None, {"data": PROMPT}, None, None])
    with pytest.raises(OpenCodeCancelled):
        send(client, cancel_event=cancel)
    assert client.calls[-1] == ("POST", "/api/session/ses_test/interrupt", {"resume": False})


def test_timeout_interrupts_async_execution():
    client = Client([None, None, {"data": PROMPT}, None, None])
    with patch("opencode_integration.client_v2.time.monotonic", side_effect=[0, 2]):
        with pytest.raises(OpenCodeError, match="timeout"):
            send(client)
    assert client.calls[-1][1].endswith("/interrupt")
    assert client.calls[-2] == ("DELETE", "/api/session/ses_test/inbox/msg_prompt", None)


def test_native_queue_admission_list_and_removal():
    queued = {"id": "msg_queued", "type": "user", "delivery": "queue",
              "payload": {"text": "follow up", "metadata": {"source": "autodeploy-queue"}}}
    client = Client([{"data": queued}, {"data": [queued, {"type": "compaction"}]}, None])
    result = client.enqueue_message("ses_test", "follow up", metadata={"source": "autodeploy-queue"})
    assert result["id"] == queued["id"]
    assert client.calls[0][2] == {"text": "follow up", "delivery": "queue", "resume": True,
                                   "metadata": {"source": "autodeploy-queue"}}
    assert client.list_message_queue("ses_test") == [queued]
    client.cancel_queued_message("ses_test", "msg_queued")
    assert client.calls[-1] == ("DELETE", "/api/session/ses_test/inbox/msg_queued", None)


def test_queue_admission_cannot_race_a_finished_observer():
    client = Client()
    with pytest.raises(OpenCodeError, match="завершён"):
        client.enqueue_message("ses_test", "follow up", require_active=True)
    assert not client.calls


def test_native_queue_preserves_separate_answers_and_returns_last_turn():
    second = {"id": "msg_second", "type": "user", "text": "second", "metadata": {"message": "second"}}
    history = page(IDLE, assistant("second answer", id="answer_second"), second,
                   assistant("first answer"), PROMPT)
    client = Client([None, None, {"data": PROMPT}, history, {"data": []}, history])
    events = []
    result = client.send_chat_message(session_id="ses_test", prompt="first", agent="autodeploy-copilot",
                                      on_event=events.append)
    assert result.text == "second answer"
    replies = [e for e in events if e["type"] == "client.queue.reply"]
    assert len(replies) == 1
    assert replies[0]["properties"]["messages"][0]["parts"][0]["text"] == "first answer"
    assert len([e for e in events if e["type"] == "client.queue.user"]) == 1
    assert not client._active_queues


def test_resume_wakes_existing_native_prompt_without_reconfiguring_session():
    queued = {"id": "msg_prompt", "type": "user", "delivery": "queue", "payload": {"text": "hello"}}
    history = page(IDLE, assistant(), PROMPT)
    client = Client([{"data": [queued]}, {"data": queued}, history, {"data": []}, history])
    events = []
    result = client.resume_message_queue("ses_test", on_event=events.append)
    assert result["parts"][0]["text"] == "done"
    assert client.calls[1] == ("POST", "/api/session/ses_test/prompt", {
        "id": "msg_prompt", "text": "hello", "resume": True, "delivery": "queue",
    })
    assert not any(path.endswith(("/model", "/agent")) for _, path, _ in client.calls)
    assert [e for e in events if e["type"] == "client.queue.user"]


def test_cancelled_resume_does_not_wake_native_queue():
    client = Client()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OpenCodeCancelled):
        client.resume_message_queue("ses_test", cancel_event=cancel)
    assert not client.calls


def test_queued_delivery_does_not_hide_failed_previous_turn():
    second = {"id": "msg_second", "type": "user", "text": "second"}
    history = page(second, {**IDLE, "outcome": "failed"}, assistant("partial"), PROMPT)
    client = Client([None, None, {"data": PROMPT}, history, None, None])
    events = []
    with pytest.raises(OpenCodeError):
        client.send_chat_message(session_id="ses_test", prompt="first", agent="autodeploy-copilot", on_event=events.append)
    assert not [event for event in events if event["type"] == "client.queue.reply"]


def test_tool_progress_and_permission_are_projected_without_raw_errors():
    raw = assistant(content=[{"type": "text", "text": "searching"}, {
        "type": "tool", "id": "call_1", "name": "repo_search", "time": {"created": 1000, "completed": 1500},
        "state": {"status": "completed", "input": {"query": "api"}, "content": [{"type": "text", "text": "found"}]},
    }])
    client = Client([None, None, {"data": PROMPT}, page(raw, PROMPT),
                     {"data": [{"id": "per_1", "sessionID": "ses_test", "action": "repo_git_pull", "resources": ["*"]}]},
                     page(IDLE, assistant("done", id="msg_final"), raw, PROMPT)])
    events = []
    assert send(client, on_event=events.append).text == "done"
    assert [e["type"] for e in events] == ["message.part.updated", "message.part.updated", "permission.asked", "message.part.updated"]
    assert events[1]["properties"]["part"]["state"]["output"] == "found"
    assert events[2]["properties"]["permission"] == "repo_git_pull"


def test_permission_reply_is_session_scoped():
    client = Client([None])
    client.respond_permission("ses_test", "per_1", "once")
    assert client.calls == [("POST", "/api/session/ses_test/permission/per_1/reply", {"decision": "once"})]
    with pytest.raises(ValueError):
        client.respond_permission("ses_test", "per_1", "allow")


def test_native_catalog_variants_enabled_models_and_agent_default():
    models = [{"providerID": "local", "id": "m", "name": "Model", "enabled": True,
               "variants": [{"id": "none"}, {"id": "high"}], "limit": {"context": 64000}},
              {"providerID": "local", "id": "disabled", "enabled": False}]
    client = Client([{"data": [{"id": "local", "name": "Local", "settings": {"apiKey": "secret"}}]},
                     {"data": models}, {"data": [{"id": "form-search", "model": {"providerID": "local", "id": "m", "variant": "none"}}]}])
    catalog = client.configured_model_catalog(agent_name="form-search")
    assert len(catalog.models) == 1
    assert catalog.models[0].variants == ("none", "high")
    assert catalog.models[0].context_limit == 64000
    assert catalog.default.variant == "none"
    assert "secret" not in repr(catalog)


def test_web_url_uses_server_scoped_route_without_credential():
    client = OpenCodeV2Client("http://127.0.0.1:4096", password="secret")
    key = base64.urlsafe_b64encode(client.base_url.encode()).decode().rstrip("=")
    assert client.session_web_url("ses_test") == f"{client.base_url}/server/{key}/session/ses_test"
    with pytest.raises(ValueError):
        client.session_web_url("../../escape")


def test_manager_waits_for_initial_agent_scan():
    client = Mock()
    client.require_agent.side_effect = [OpenCodeAgentMissingError("loading"), None, None, None, None, None]
    OpenCodeManager._require_agents(client, timeout=1)
    assert client.require_agent.call_count == 6


def test_owned_server_overrides_both_password_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_PASSWORD", "shell-secret")
    manager = OpenCodeManager(Path(__file__).parents[1], runtime_dir=tmp_path)
    with patch("opencode_integration.manager.subprocess.Popen") as popen, patch.object(manager, "_start_stream_loggers"):
        manager._spawn("opencode", 4097)
    env = popen.call_args.kwargs["env"]
    assert env["OPENCODE_PASSWORD"] == env["OPENCODE_SERVER_PASSWORD"] == manager._owned_password
    assert len(manager._owned_password) >= 32
    assert manager._owned_password != "shell-secret"
    assert manager.password == ""
    assert popen.call_args.args[0] == ["opencode", "serve", "--hostname", "127.0.0.1", "--port", "4097"]


def test_runtime_removes_stale_native_and_legacy_autodeploy_entries(tmp_path):
    config = {"mcp": {"autodeploy": {"type": "remote", "url": "old"}, "servers": {
        "autodeploy": {"type": "remote", "url": "old"}, "other": {"type": "remote", "url": "keep"},
    }}}
    (tmp_path / "opencode.json").write_text(json.dumps(config))
    manager = OpenCodeManager(Path(__file__).parents[1], runtime_dir=tmp_path)
    manager._prepare_runtime()
    result = json.loads((tmp_path / "opencode.json").read_text())
    assert "autodeploy" not in result["mcp"]
    assert result["mcp"]["servers"] == {"other": {"type": "remote", "url": "keep"}}
