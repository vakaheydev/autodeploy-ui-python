from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opencode_integration.client import OpenCodeClient, OpenCodeHttpError
from opencode_integration.client_v2 import _permission
from opencode_integration.copilot import UnifiedCopilot
from webapp.ai_api import router
from webapp.ai_service import WebAIService, WebCopilotSession


def setup_permission():
    request = _permission({"id": "per_test", "sessionID": "ses_test", "action": "example_read",
                           "resources": ["example"], "save": ["example"]})
    client = Mock()
    client.list_pending_permissions.return_value = [request]
    copilot = UnifiedCopilot(client, Mock(), Mock(), forms=[], workflow_id="test")
    copilot._session_id = "ses_test"
    return request, client, copilot


@pytest.mark.parametrize("allow,always,decision", [
    (True, False, "once"), (False, False, "reject"), (True, True, "always"),
])
def test_permission_http_to_native_reply_and_resolution_event(allow, always, decision):
    request, client, copilot = setup_permission()
    service = WebAIService(SimpleNamespace())
    session = WebCopilotSession("chat", copilot, "local", "model", "none", (), Mock(), busy=True)
    service._sessions["chat"] = session
    app = FastAPI()
    app.state.container = SimpleNamespace(ai=service)
    app.include_router(router)
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/sessions/chat/permissions/per_test", json={"allow": allow, "always": always})
    assert result.json() == {"accepted": True, "decision": decision}
    client.respond_permission.assert_called_once_with("ses_test", "per_test", decision)
    assert session.events[-1].payload["kind"] == "permission_resolved"
    assert session.events[-1].payload["detail"] == decision


def test_stale_or_foreign_permission_is_not_submitted():
    request, client, copilot = setup_permission()
    request["sessionID"] = "ses_other"
    assert copilot.approve_permission("per_test", allow=True) is False
    client.respond_permission.assert_not_called()


def test_always_requires_explicit_savable_rule():
    request, client, copilot = setup_permission()
    request["always"] = []
    with pytest.raises(ValueError, match="сохраняемое"):
        copilot.approve_permission("per_test", allow=True, always=True)
    with pytest.raises(ValueError, match="отклонением"):
        copilot.approve_permission("per_test", allow=False, always=True)
    client.respond_permission.assert_not_called()


def test_permission_disappearing_during_reply_is_expired():
    request, client, copilot = setup_permission()
    client.respond_permission.side_effect = OpenCodeHttpError(404, "request missing")
    client.list_pending_permissions.side_effect = [[request], []]
    assert copilot.approve_permission("per_test", allow=False) is False


def test_transport_error_keeps_permission_retryable():
    request, client, copilot = setup_permission()
    client.respond_permission.side_effect = OpenCodeHttpError(503, "temporarily unavailable")
    with pytest.raises(OpenCodeHttpError):
        copilot.approve_permission("per_test", allow=True)
    client.respond_permission.side_effect = None
    assert copilot.approve_permission("per_test", allow=True)


def test_poll_detects_resolution_without_sse_and_copilot_projects_save_scope():
    request, _, copilot = setup_permission()
    client = OpenCodeClient("http://127.0.0.1:4096")
    client.list_pending_permissions = Mock(side_effect=[[request], OSError("offline"), []])
    events = []
    copilot._on_event = events.append
    seen = set()
    client._poll_pending_permissions("ses_test", seen, copilot._handle_raw_event)
    assert events[-1].permission_always is True
    assert events[-1].permission_scope == "project"
    assert events[-1].permission_resources == ("example",)
    client._poll_pending_permissions("ses_test", seen, copilot._handle_raw_event)
    assert len(events) == 1
    client._poll_pending_permissions("ses_test", seen, copilot._handle_raw_event)
    assert events[-1].kind == "permission_resolved"
    assert events[-1].permission_id == "per_test"
