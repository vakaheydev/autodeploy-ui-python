from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType
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


def test_block_proposals_are_expanded_to_reviewable_repeated_leaf_paths() -> None:
    fields = [FieldDefinition(
        "plan",
        "План",
        FieldType.BLOCK,
        plural=True,
        plural_max=3,
        block_fields=[
            FieldDefinition("name", "Название", FieldType.TEXT),
            FieldDefinition("enabled", "Включён", FieldType.CHECKBOX),
        ],
    )]
    definitions = FormDraftStore._field_definitions(fields)

    proposals = FormDraftStore._parse_proposals([{
        "field_path": "plan",
        "value": [
            {"name": "Основной", "enabled": True},
            {"name": "Резервный", "enabled": False},
        ],
        "confidence": "high",
        "source": "OPERATOR",
    }], definitions)

    assert [(item.field_path, item.value) for item in proposals] == [
        ("plan.name", "Основной"),
        ("plan.enabled", True),
        ("plan_2.name", "Резервный"),
        ("plan_2.enabled", False),
    ]
    assert FormDraftStore._definition_for_path(
        definitions, "plan_2.name"
    ).label == "Название"


def test_common_zero_based_plural_paths_are_normalized() -> None:
    fields = [FieldDefinition(
        "plan",
        "План",
        FieldType.BLOCK,
        plural=True,
        plural_max=3,
        block_fields=[FieldDefinition("name", "Название", FieldType.TEXT)],
    )]
    definitions = FormDraftStore._field_definitions(fields)

    proposals = FormDraftStore._parse_proposals([
        {
            "field_path": "plan[0].name",
            "value": "Основной",
            "confidence": "high",
            "source": "OPERATOR",
        },
        {
            "field_path": "plan.1.name",
            "value": "Резервный",
            "confidence": "high",
            "source": "OPERATOR",
        },
        {
            "field_path": "plan[2].name",
            "value": "Аварийный",
            "confidence": "high",
            "source": "OPERATOR",
        },
    ], definitions)

    assert [item.field_path for item in proposals] == [
        "plan.name",
        "plan_2.name",
        "plan_3.name",
    ]


def test_prepared_ai_draft_exposes_each_repeated_block_value_for_review(
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DynamicBlockForm(BaseForm):
        @property
        def form_id(self) -> str:
            return "test.dynamic-block-review"

        @property
        def title(self) -> str:
            return "Dynamic block review"

        @property
        def category(self) -> str:
            return "other"

        @property
        def fields(self) -> list[FieldDefinition]:
            return [FieldDefinition(
                "plan",
                "План",
                FieldType.BLOCK,
                required=False,
                plural=True,
                plural_max=3,
                block_fields=[
                    FieldDefinition("name", "Название", FieldType.TEXT),
                    FieldDefinition(
                        "enabled", "Включён", FieldType.CHECKBOX, required=False
                    ),
                ],
            )]

        def build_payload(self, form_data):
            return dict(form_data)

        def get_submit_endpoint(self, environment: str) -> str:
            return "https://example.invalid"

    form = DynamicBlockForm()
    monkeypatch.setattr(
        container.forms,
        "get_form",
        lambda _form_id, _environment="": form,
    )
    document = container.forms.describe(form.form_id, "test_int")
    assert document["fields"][0]["plural_contract"] == {
        "first_instance_path": "plan",
        "additional_instance_path_template": "plan_{instance_number}",
        "additional_instance_number_starts_at": 2,
        "draft_array_supported": True,
    }

    draft = FormDraftStore(container).prepare(
        workflow_id="workflow-dynamic-block-review",
        form_id=form.form_id,
        environment="test_int",
        version=document["version"],
        proposals=[{
            "field_path": "plan",
            "value": [
                {"name": "Основной", "enabled": True},
                {"name": "Резервный", "enabled": False},
                {"name": "Аварийный", "enabled": True},
            ],
            "confidence": "high",
            "source": "OPERATOR",
        }],
    )

    assert draft.values["plan"] == {"name": "Основной", "enabled": True}
    assert draft.values["plan_2"] == {"name": "Резервный", "enabled": False}
    assert draft.values["plan_3"] == {"name": "Аварийный", "enabled": True}
    assert [item["key"] for item in draft.fields] == [
        "plan.name",
        "plan.enabled",
        "plan_2.name",
        "plan_2.enabled",
        "plan_3.name",
        "plan_3.enabled",
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


def test_pending_ticket_draft_is_filled_in_place_for_inline_review(
    container: ApplicationContainer,
) -> None:
    store = FormDraftStore(container)
    document = container.forms.describe("api.create", "test_int")
    current = {**document["initial_values"], "name": "Operator value"}
    pending = store.begin_ai_fill(
        workflow_id="workflow-ticket-fill",
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        current_values=current,
    )

    assert pending.status == "running"
    assert pending.values["name"] == "Operator value"

    completed = store.prepare(
        workflow_id="workflow-ticket-fill",
        form_id="api.create",
        environment="test_int",
        version=document["version"],
        draft_id=pending.id,
        proposals=_proposals(),
    )

    assert completed is pending
    assert completed.status == "complete"
    assert completed.progress == "Черновик Copilot готов"
    assert completed.revision == 2
    assert completed.baseline["name"] == "Operator value"
    assert completed.values["name"] == "Orders API"


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
