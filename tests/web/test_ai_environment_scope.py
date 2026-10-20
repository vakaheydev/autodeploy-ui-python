import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opencode_integration.prompts import MCP_COPILOT_SYSTEM_RULES, build_copilot_environment_context
from opencode_integration.researcher import RESEARCHER_SYSTEM_RULES
from webapp.ai_service import WebAIService, WebCopilotSession


def service_with_active_default():
    service = WebAIService(SimpleNamespace(opencode_manager=SimpleNamespace(client=Mock())))
    copilot = SimpleNamespace(mcp_native=True, repository_mcp="repo")
    session = WebCopilotSession("chat", copilot, "local", "model", "none", ("none",), Mock(),
                                busy=True, job_id="job", active_environment="test_int",
                                cancel_event=threading.Event())
    service._sessions["chat"] = session
    return service, session


def test_research_can_target_another_verified_scope(monkeypatch):
    service, session = service_with_active_default()
    researcher = Mock()
    researcher.research.return_value = SimpleNamespace(summary="evidence", thinking="none",
                                                       opencode_seconds=1, generation_seconds=1)
    monkeypatch.setattr("webapp.ai_service.RepositoryResearcher", lambda _: researcher)
    assert service.research_repository("chat", question="Compare scopes", environment="verified_other_scope")["summary"] == "evidence"
    assert researcher.research.call_args.kwargs["environment"] == "verified_other_scope"
    assert session.active_environment == "test_int"


def test_draft_can_target_another_valid_environment_without_changing_default():
    service, session = service_with_active_default()
    draft = SimpleNamespace(id="draft", form_id="api.create", environment="prod_int", form_version="v",
                            revision=1, status="ready", snapshot=lambda: {"result": {"valid": True}})
    service._drafts.prepare = Mock(return_value=draft)
    result = service.prepare_form_draft("chat", form_id="api.create", environment="prod_int",
                                        form_version="v", proposals=[])
    assert result["environment"] == "prod_int"
    assert session.active_environment == "test_int"
    with pytest.raises(ValueError, match="Неизвестное"):
        service.prepare_form_draft("chat", form_id="api.create", environment="invented",
                                    form_version="v", proposals=[])


def test_all_ai_contexts_explain_default_scope_and_preserve_entity_id_boundaries():
    for text in (MCP_COPILOT_SYSTEM_RULES, RESEARCHER_SYSTEM_RULES, build_copilot_environment_context("test_int")):
        assert "not an access boundary" in text
        assert "do not invent scope names" in text
        assert "independently in every target environment" in text
