from __future__ import annotations

import time
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
