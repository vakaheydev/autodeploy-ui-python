from __future__ import annotations

import time
import threading
from types import SimpleNamespace

import pytest

from webapp.ai_service import AIHandoff, ExtractionJob, WebAIService
from webapp.ai_drafts import FormDraft


def handoff(token: str = "handoff") -> AIHandoff:
    return AIHandoff(
        token=token,
        session_id="session",
        form_id="api.create",
        context=None,
        extraction=None,  # type: ignore[arg-type]
        provider_id="corp",
        model_id="model",
        variants=("none", "low"),
        created_at=time.time(),
    )


def test_handoff_capability_can_only_start_one_extraction() -> None:
    service = WebAIService(SimpleNamespace())
    value = handoff()
    service._handoffs[value.token] = value

    assert service._take_handoff(value.token) is value
    with pytest.raises(KeyError, match="handoff"):
        service._take_handoff(value.token)


def test_extractor_setup_failure_finishes_job_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WebAIService(SimpleNamespace())
    job = ExtractionJob("job", handoff(), "test_int", {})

    def fail(_job: ExtractionJob) -> None:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(service, "_run_extraction", fail)
    service._extract_worker(job)

    assert job.status == "error"
    assert job.error == "provider unavailable"


def test_native_outcome_exposes_every_draft_in_a_multi_form_turn() -> None:
    service = WebAIService(SimpleNamespace())
    now = time.time()
    for index, form_id in enumerate(("api.create", "apps.deploy"), start=1):
        draft = FormDraft(
            id=f"draft-{index}",
            workflow_id="workflow",
            form_id=form_id,
            environment="test_int",
            form_version="version",
            baseline={},
            values={},
            fields=[],
            warnings=[],
            errors=[],
            valid=True,
            created_at=now,
            updated_at=now,
            expires_at=now + 100,
        )
        service._drafts._drafts[draft.id] = draft

    session = SimpleNamespace(
        copilot=SimpleNamespace(mcp_native=True),
        job_id="job",
        turn_candidates=[],
        turn_candidates_job_id="",
        turn_draft_ids=["draft-1", "draft-2"],
        turn_draft_job_id="job",
    )
    outcome = SimpleNamespace(
        answer="Подготовлены две формы",
        opencode_seconds=1.0,
        generation_seconds=0.5,
    )

    payload = service._outcome_payload(session, outcome)

    assert payload["intent"] == "execution_plan"
    assert payload["selected_form_id"] is None
    assert [item["form_id"] for item in payload["drafts"]] == [
        "api.create", "apps.deploy",
    ]


def test_persisted_opencode_history_is_restored_for_chat_switching() -> None:
    events = WebAIService._history_from_opencode([
        {
            "info": {"role": "user", "variant": "low", "time": {"created": 1_000}},
            "parts": [{
                "type": "text",
                "text": "BEGIN_OPERATOR_REQUEST\n\"Найди API\"\nEND_OPERATOR_REQUEST",
            }],
        },
        {
            "info": {
                "role": "assistant",
                "variant": "low",
                "time": {"created": 1_100, "completed": 2_600},
            },
            "parts": [
                {
                    "id": "tool-1",
                    "type": "tool",
                    "tool": "gravitee_repo_get_api",
                    "state": {
                        "status": "completed",
                        "input": {"name": "Payments"},
                        "output": {"id": "api-1"},
                        "time": {"start": 1_200, "end": 2_200},
                    },
                },
                {"type": "text", "text": "API найден."},
            ],
        },
    ])

    assert [event.kind for event in events] == ["system", "user", "agent_event", "assistant"]
    assert events[1].payload["text"] == "Найди API"
    assert events[2].payload["call_id"] == "tool-1"
    assert events[2].payload["duration_seconds"] == 1.0
    assert "api-1" in events[2].payload["output_detail"]
    assert events[3].payload["elapsed_seconds"] == 1.5


def test_restored_chat_rebuilds_permanent_draft_link_from_mcp_result() -> None:
    events = WebAIService._history_from_opencode([{
        "info": {
            "role": "assistant",
            "variant": "none",
            "time": {"created": 1_000, "completed": 2_000},
        },
        "parts": [
            {
                "id": "tool-draft",
                "type": "tool",
                "tool": "gravitee_autodeploy_prepare_form_draft",
                "state": {
                    "status": "completed",
                    "input": {"form_id": "api.create"},
                    "output": {
                        "draft_id": "persistent-draft",
                        "form_id": "api.create",
                        "environment": "test_int",
                        "valid": True,
                    },
                },
            },
            {"type": "text", "text": "Форма заполнена."},
        ],
    }])

    assistant = next(event for event in events if event.kind == "assistant")
    assert assistant.payload["selected_form_id"] == "api.create"
    assert assistant.payload["draft_id"] == "persistent-draft"


def test_persisted_history_keeps_model_notes_between_tool_calls() -> None:
    events = WebAIService._history_from_opencode([
        {
            "info": {"role": "user", "variant": "none", "time": {"created": 1_000}},
            "parts": [{
                "type": "text",
                "text": "BEGIN_OPERATOR_REQUEST\n\"Скопируй API\"\nEND_OPERATOR_REQUEST",
            }],
        },
        {
            "info": {
                "role": "assistant",
                "variant": "none",
                "tokens": {"total": 321},
                "time": {"created": 1_100, "completed": 5_100},
            },
            "parts": [
                {"id": "text-1", "type": "text", "text": "Сначала получу схему формы."},
                {"id": "tool-1", "type": "tool", "tool": "get_form_schema", "state": {"status": "completed", "input": {}, "output": {"ok": True}}},
                {"id": "text-2", "type": "text", "text": "Теперь читаю исходный API."},
                {"id": "tool-2", "type": "tool", "tool": "get_api", "state": {"status": "completed", "input": {}, "output": {"id": "api"}}},
                {"id": "text-3", "type": "text", "text": "Черновик готов."},
            ],
        },
    ])

    assert [event.kind for event in events] == [
        "system", "user", "assistant_note", "agent_event",
        "assistant_note", "agent_event", "assistant",
    ]
    assert events[2].payload["text"] == "Сначала получу схему формы."
    assert events[4].payload["text"] == "Теперь читаю исходный API."
    assert events[-1].payload["text"] == "Черновик готов."
    assert events[-1].payload["tokens_used"] == 321


def test_short_title_does_not_copy_the_whole_operator_question() -> None:
    assert WebAIService._short_title(
        "А ты можешь, пожалуйста, создать такую же API, только с новым путём?"
    ) == "Создать API новым путём"


def test_manual_chat_title_is_persisted_in_opencode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.updated: tuple[str, str] | None = None

        def update_session_title(self, session_id: str, title: str) -> None:
            self.updated = session_id, title

    client = Client()
    service = WebAIService(SimpleNamespace(
        opencode_manager=SimpleNamespace(client=client),
    ))
    session = SimpleNamespace(
        title="Старое название",
        title_custom=False,
        copilot=SimpleNamespace(session_id="ses-1"),
        condition=threading.Condition(),
    )
    service._sessions["chat-1"] = session
    monkeypatch.setattr(service, "snapshot", lambda *_args, **_kwargs: {"title": session.title})

    result = service.rename("chat-1", "  Новый   короткий чат  ")

    assert result == {"title": "Новый короткий чат"}
    assert session.title_custom is True
    assert client.updated == ("ses-1", "Новый короткий чат")
