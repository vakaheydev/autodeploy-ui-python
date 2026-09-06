from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from webapp.ai_drafts import FormDraftStore
from webapp.api import submit_form
from webapp.container import ApplicationContainer
from webapp.models import SubmitRequest
from webapp.settings import WebSettings


def _settings(tmp_path: Path) -> WebSettings:
    root = Path(__file__).resolve().parents[2]
    return WebSettings(
        host="127.0.0.1",
        port=8765,
        project_root=root,
        data_dir=tmp_path / "data",
        env_file=tmp_path / ".env",
        static_dir=root / "webapp" / "static",
        log_dir=tmp_path / "logs",
        max_request_bytes=2 * 1024 * 1024,
        auto_connect_opencode=False,
        open_browser=False,
        mcp_enabled=True,
    )


@pytest.fixture
def container(tmp_path: Path):
    value = ApplicationContainer(_settings(tmp_path))
    yield value
    value.opencode_manager.stop()


def _proposals(context_path: str = "/orders/v1"):
    return [
        {"field_path": "name", "value": "Orders API", "confidence": "high", "source": "OPERATOR"},
        {"field_path": "owner", "value": "Payments", "confidence": "high", "source": "OPERATOR"},
        {"field_path": "category", "value": "Внутреннее АПИ", "confidence": "medium", "source": "OPERATOR"},
        {"field_path": "context_path", "value": context_path, "confidence": "high", "source": "OPERATOR"},
        {"field_path": "endpoint_type", "value": "REST", "confidence": "high", "source": "OPERATOR"},
    ]


def test_python_draft_resolves_references_validates_and_is_idempotent(
    container: ApplicationContainer,
) -> None:
    store = FormDraftStore(container)
    document = container.forms.describe("api.create", "test_int")

    draft = store.prepare(
        workflow_id="workflow-12345678901234567890",
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        proposals=_proposals(),
    )
    duplicate = store.prepare(
        workflow_id="workflow-12345678901234567890",
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        proposals=_proposals(),
    )

    assert duplicate is draft
    assert draft.revision == 1
    assert draft.valid is True
    assert draft.values["category"] == "internal"
    assert draft.values["endpoint_type"] == "rest"
    assert {item["key"] for item in draft.fields} == {
        "name", "owner", "category", "context_path", "endpoint_type",
    }
    assert draft.snapshot()["result"]["baseline"] == document["initial_values"]


def test_draft_refinement_preserves_id_and_rejects_unknown_fields(
    container: ApplicationContainer,
) -> None:
    store = FormDraftStore(container)
    document = container.forms.describe("api.create", "test_int")
    workflow = "workflow-12345678901234567890"
    draft = store.prepare(
        workflow_id=workflow,
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        proposals=_proposals(),
    )
    store.begin_refinement(draft.id, current_values=draft.values)
    revised = store.prepare(
        workflow_id=workflow,
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        draft_id=draft.id,
        proposals=_proposals("/orders/v2"),
    )

    assert revised.id == draft.id
    assert revised.revision == 2
    assert revised.values["context_path"] == "/orders/v2"
    assert revised.status == "complete"

    with pytest.raises(ValueError, match="Неизвестное поле"):
        store.prepare(
            workflow_id=workflow,
            form_id="api.create",
            environment="test_int",
            version=document["version"],
            proposals=[{
                "field_path": "made_up",
                "value": "x",
                "confidence": "high",
                "source": "OPERATOR",
            }],
        )


def test_refinement_preserves_manual_values_and_only_pending_review_fields(
    container: ApplicationContainer,
) -> None:
    store = FormDraftStore(container)
    document = container.forms.describe("api.create", "test_int")
    workflow = "workflow-12345678901234567890"
    draft = store.prepare(
        workflow_id=workflow,
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        proposals=_proposals(),
    )
    current = dict(draft.values)
    current["name"] = "Operator edited name"

    store.begin_refinement(
        draft.id,
        current_values=current,
        pending_fields=["context_path"],
    )
    revised = store.prepare(
        workflow_id=workflow,
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        draft_id=draft.id,
        proposals=[{
            "field_path": "context_path",
            "value": "/orders/v3",
            "confidence": "high",
            "source": "OPERATOR_REFINEMENT",
        }],
    )

    assert revised.values["name"] == "Operator edited name"
    assert revised.baseline["name"] == "Operator edited name"
    assert "context_path" not in revised.baseline
    assert [item["key"] for item in revised.fields] == ["context_path"]


def test_failed_refinement_does_not_replace_previous_draft(
    container: ApplicationContainer,
) -> None:
    store = FormDraftStore(container)
    document = container.forms.describe("api.create", "test_int")
    draft = store.prepare(
        workflow_id="workflow-12345678901234567890",
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        proposals=_proposals(),
    )
    before = draft.snapshot()["result"]
    current = dict(draft.values)
    current["name"] = "Uncommitted edit"
    store.begin_refinement(
        draft.id,
        current_values=current,
        pending_fields=["context_path"],
    )
    store.fail(draft.id, "provider failed")

    after = draft.snapshot()
    assert after["status"] == "error"
    assert after["result"] == before


def test_manual_draft_is_persistent_until_explicit_delete(
    container: ApplicationContainer,
) -> None:
    document = container.forms.describe("api.create", "test_int")
    store = FormDraftStore(container)
    draft = store.save_values(
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        values={"name": "Незавершённый API"},
    )

    assert draft.source == "manual"
    assert draft.expires_at == 0
    assert (container.settings.data_dir / "drafts.json").is_file()

    restored = FormDraftStore(container).require(draft.id)
    assert restored.values["name"] == "Незавершённый API"
    assert restored.source == "manual"

    store.delete(draft.id)
    assert FormDraftStore(container).get(draft.id) is None


def test_ai_draft_survives_workflow_and_process_lifecycle(
    container: ApplicationContainer,
) -> None:
    document = container.forms.describe("api.create", "test_int")
    store = FormDraftStore(container)
    draft = store.prepare(
        workflow_id="workflow-persistent",
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        proposals=_proposals(),
    )

    store.delete_workflow("workflow-persistent")

    restored = FormDraftStore(container).require(draft.id)
    assert restored.workflow_id == "workflow-persistent"
    assert restored.source == "ai"
    assert restored.fields

    reviewed = store.save_values(
        form_id=draft.form_id,
        environment=draft.environment,
        version=draft.form_version,
        values=draft.values,
        draft_id=draft.id,
        pending_review_fields=["context_path"],
    )
    assert [item["key"] for item in reviewed.fields] == ["context_path"]
    assert [item["key"] for item in FormDraftStore(container).require(draft.id).fields] == ["context_path"]


def test_successful_submit_deletes_the_exact_draft() -> None:
    deleted: list[str] = []
    fake_container = SimpleNamespace(
        ai=SimpleNamespace(
            draft=lambda draft_id: {
                "id": draft_id,
                "form_id": "api.create",
                "environment": "test_int",
            },
            delete_draft=deleted.append,
        ),
        forms=SimpleNamespace(submit=lambda *_args: {"success": True}),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        container=fake_container,
    )))

    result = submit_form(
        "api.create",
        SubmitRequest(
            environment="test_int",
            values={"name": "Orders"},
            form_version="v1",
            confirmation_token="",
            draft_id="draft-1",
        ),
        request,  # type: ignore[arg-type]
    )

    assert result == {"success": True}
    assert deleted == ["draft-1"]
