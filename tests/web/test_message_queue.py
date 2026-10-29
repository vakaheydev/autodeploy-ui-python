from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.environments import OPENCODE_MESSAGE_QUEUE_KEY
from webapp.ai_service import WebAIService, WebCopilotSession


def make_service(*, supported=True, enabled="true"):
    copilot = SimpleNamespace(
        queued_messages=Mock(return_value=[]), enqueue_message=Mock(return_value={"id": "msg_native"}),
        remove_queued_message=Mock(), cancel=Mock(), mcp_native=True, session_id="ses_native",
        steer_queued_message=Mock(), reorder_queued_messages=Mock(),
    )
    service = WebAIService(SimpleNamespace(env_manager=SimpleNamespace(
        load=lambda: {OPENCODE_MESSAGE_QUEUE_KEY: enabled},
    )))
    service._reference_mentions = SimpleNamespace(resolve=lambda *_: [])
    session = WebCopilotSession(
        "chat", copilot, "provider", "model", "none", ("none",), SimpleNamespace(cancel=Mock()),
        busy=True, queue_supported=supported, queue_ready=True, active_thinking="none",
        active_environment="test_int",
    )
    service._sessions[session.id] = session
    return service, session


def send(service, **extra):
    args = dict(message="Следующее сообщение", environment="test_int", ticket_id=None,
                provider_id="provider", model_id="model", thinking="auto")
    return service.start_message("chat", **{**args, **extra})


def test_busy_message_is_admitted_to_opencode_immediately():
    service, session = make_service()
    assert send(service) == {"queued": True, "queue_id": "msg_native"}
    session.copilot.enqueue_message.assert_called_once()
    assert session.copilot.enqueue_message.call_args.kwargs["metadata"]["source"] == "autodeploy-queue"
    assert session.busy
    assert not any(event.kind == "user" for event in session.events)


def test_immediate_message_uses_native_steer_even_when_queue_admission_is_disabled():
    service, session = make_service(enabled="false")
    assert send(service, delivery="steer")["queue_id"] == "msg_native"
    assert session.copilot.enqueue_message.call_args.kwargs["delivery"] == "steer"
    assert session.copilot.enqueue_message.call_args.kwargs["metadata"]["message"] == "Следующее сообщение"
    session.copilot.cancel.assert_not_called()


def test_queue_controls_use_existing_native_items():
    service, session = make_service()
    service.send_queued_message("chat", "msg_native")
    session.copilot.steer_queued_message.assert_called_once_with("msg_native")
    service.reorder_queue("chat", ["msg_b", "msg_a"])
    session.copilot.reorder_queued_messages.assert_called_once_with(["msg_b", "msg_a"])
    session.copilot.enqueue_message.assert_not_called()


def test_paused_send_now_observes_the_selected_message(monkeypatch):
    service, session = make_service()
    session.busy = False
    session.copilot.queued_messages.return_value = [{"id": id_, "payload": {"metadata": {
        "source": "autodeploy-queue", "environment": "test_int", "provider_id": "provider",
        "model_id": "model", "thinking": "none",
    }}} for id_ in ["first", "selected"]]
    start = Mock(return_value={"job_id": "observer"})
    monkeypatch.setattr(service, "start_message", start)
    service.send_queued_message("chat", "selected")
    assert start.call_args.kwargs["_resume_message_id"] == "selected"
    with pytest.raises(RuntimeError, match="уже отправлено"):
        service.send_queued_message("chat", "missing")


@pytest.mark.parametrize("supported,enabled", [(False, "true"), (True, "false")])
def test_queue_is_gated_by_adapter_and_setting(supported, enabled):
    service, session = make_service(supported=supported, enabled=enabled)
    with pytest.raises(RuntimeError, match="OpenCode v2"):
        send(service)
    session.copilot.enqueue_message.assert_not_called()


@pytest.mark.parametrize("extra", [{"model_id": "another"}, {"thinking": "high"}])
def test_queue_cannot_change_active_session_model(extra):
    service, session = make_service()
    with pytest.raises(ValueError, match="окружение, модель"):
        send(service, **extra)
    session.copilot.enqueue_message.assert_not_called()


def test_queue_limit_and_preparation_are_checked_before_admission():
    service, session = make_service()
    session.queue_ready = False
    with pytest.raises(RuntimeError, match="начала ответа"):
        send(service)
    session.queue_ready = True
    session.copilot.queued_messages.return_value = [{}] * 10
    with pytest.raises(RuntimeError, match="заполнена"):
        send(service)
    session.copilot.enqueue_message.assert_not_called()


def test_queue_snapshot_and_removal_use_remote_inbox_not_local_history():
    service, session = make_service()
    row = {"id": "msg_remote", "type": "user", "payload": {"text": "PRIVATE_CONTEXT", "metadata": {
        "source": "autodeploy-queue", "message": "Второй запрос", "environment": "test_int", "model_id": "model",
    }}}
    session.copilot.queued_messages.return_value = [row]
    state = service.message_queue("chat")
    assert state["queue"][0]["message"] == "Второй запрос"
    assert "PRIVATE_CONTEXT" not in str(state)
    service.remove_queued_message("chat", "msg_remote")
    session.copilot.remove_queued_message.assert_called_once_with("msg_remote")


def test_stop_preserves_pending_native_messages():
    service, session = make_service()
    service.cancel("chat")
    session.copilot.cancel.assert_called_once()
    session.copilot.remove_queued_message.assert_not_called()


def test_refinement_does_not_accept_followups_with_a_different_draft_scope():
    service, session = make_service()
    session.refining_draft_id = "draft"
    with pytest.raises(RuntimeError, match="черновиком"):
        send(service)
    session.copilot.enqueue_message.assert_not_called()


def test_queue_read_failure_after_admission_does_not_report_send_failure():
    service, session = make_service()
    session.copilot.queued_messages.side_effect = [[], OSError("offline")]
    assert send(service)["queued"] is True
    session.copilot.enqueue_message.assert_called_once()


def test_native_answer_uses_its_own_tool_results_instead_of_later_draft():
    service, session = make_service()
    session.turn_candidates = [{"form_id": "wrong-later-form"}]
    session.turn_candidates_job_id = session.job_id
    messages = ({"info": {"role": "assistant"}, "parts": [
        {"type": "tool", "tool": "autodeploy_semantic_search_forms", "state": {
            "status": "completed", "output": {"items": [{"form_id": "right-form", "title": "Right"}]},
        }},
        {"type": "text", "text": "Выберите форму"},
    ]},)
    payload = service._outcome_payload(session, SimpleNamespace(messages=messages))
    assert payload["form_candidates"][0]["form_id"] == "right-form"


def test_queue_http_contracts():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from webapp.ai_api import router

    service, session = make_service()
    app = FastAPI()
    app.state.container = SimpleNamespace(ai=service)
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/v1/ai/sessions/chat/queue").json()["queue_supported"] is True
        assert client.delete("/api/v1/ai/sessions/chat/queue/msg_native").status_code == 200
        assert client.post("/api/v1/ai/sessions/chat/queue/resume").status_code == 409
        assert client.post("/api/v1/ai/sessions/chat/queue/msg_native/send").status_code == 202
        assert client.post("/api/v1/ai/sessions/chat/queue/reorder", json={"message_ids": ["b", "a"]}).status_code == 200
        assert client.post("/api/v1/ai/sessions/chat/queue/reorder", json={"message_ids": []}).status_code == 422
    session.copilot.remove_queued_message.assert_called_once_with("msg_native")


def test_paused_queue_resumes_existing_native_ids(monkeypatch):
    service, session = make_service()
    session.busy = False
    session.copilot.queued_messages.return_value = [{"id": "msg_saved", "payload": {"metadata": {
        "source": "autodeploy-queue", "environment": "test_int", "provider_id": "provider",
        "model_id": "model", "thinking": "none",
    }}}]
    start = Mock(return_value={"job_id": "observer"})
    monkeypatch.setattr(service, "start_message", start)
    service.resume_queue("chat")
    assert start.call_args.kwargs["_resume_queue"] is True
    session.copilot.enqueue_message.assert_not_called()
