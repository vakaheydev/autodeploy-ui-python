from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from webapp.ai_service import AIHandoff, ExtractionJob, WebAIService


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
