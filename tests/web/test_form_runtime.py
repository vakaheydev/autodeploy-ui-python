from __future__ import annotations

from pathlib import Path

import pytest

from forms.base_form import BaseForm, ServerAction
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from forms.loader import register_all_forms
from forms.registry import FormRegistry
from webapp.container import ApplicationContainer
from webapp.form_runtime import form_version
from webapp.settings import WebSettings
from services.submit_service import SubmitService


def settings(tmp_path: Path) -> WebSettings:
    return WebSettings(
        host="127.0.0.1",
        port=8765,
        project_root=Path(__file__).resolve().parents[2],
        data_dir=tmp_path / "data",
        env_file=tmp_path / ".env",
        static_dir=Path(__file__).resolve().parents[2] / "webapp" / "static",
        log_dir=tmp_path / "logs",
        max_request_bytes=2 * 1024 * 1024,
        auto_connect_opencode=False,
        open_browser=False,
    )


@pytest.fixture
def container(tmp_path: Path):
    value = ApplicationContainer(settings(tmp_path))
    yield value
    value.opencode_manager.stop()


def test_existing_python_form_is_projected_and_validated(container: ApplicationContainer) -> None:
    summary = next(item for item in container.forms.list_forms() if item["id"] == "api.create")
    assert "Название АПИ" in summary["keywords"]
    document = container.forms.describe("api.create", "test_int")
    assert document["title"] == "Создание АПИ"
    category = next(field for field in document["fields"] if field["key"] == "category")
    assert {item["id"] for item in category["options"]} >= {"internal", "external"}

    values = {
        "name": "Orders API",
        "description": "Orders",
        "owner": "Payments",
        "category": "internal",
        "context_path": "/orders/v1",
        "endpoint_type": "rest",
    }
    validation = container.forms.validate(
        "api.create", "test_int", values, document["version"]
    )
    assert validation.valid, validation.errors
    preview = container.forms.preview(
        "api.create", "test_int", values, document["version"]
    )
    assert preview["valid"] is True
    assert preview["payload"]["contextPath"] == "/orders/v1"


def test_unknown_fields_and_reference_ids_are_rejected(container: ApplicationContainer) -> None:
    document = container.forms.describe("api.create", "test_int")
    validation = container.forms.validate(
        "api.create",
        "test_int",
        {
            "name": "Orders",
            "owner": "Team",
            "category": "does-not-exist",
            "context_path": "/orders",
            "endpoint_type": "rest",
            "browser_only_rule": True,
        },
        document["version"],
    )
    codes = {item["code"] for item in validation.errors}
    assert "unknown_field" in codes
    assert "invalid_reference" in codes


def test_required_field_error_is_not_duplicated_by_base_form_validation(
    container: ApplicationContainer,
) -> None:
    document = container.forms.describe("api.create", "test_int")
    validation = container.forms.validate(
        "api.create", "test_int", {}, document["version"]
    )
    name_errors = [
        item for item in validation.errors if item.get("field") == "name"
    ]
    assert name_errors == [{
        "field": "name",
        "code": "required",
        "message": 'Поле "Название АПИ" обязательно',
    }]
    assert not any(
        item["message"] == 'Поле "Название АПИ" обязательно для заполнения'
        for item in validation.errors
    )


def test_legacy_condition_key_access_treats_unfilled_fields_as_none(
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ConditionalForm(BaseForm):
        form_id = "test.legacy-condition"
        title = "Legacy condition"
        category = "other"
        fields = [
            FieldDefinition("plan_type", "Plan type", FieldType.SELECT, required=False),
            FieldDefinition(
                "plan_jwt_type",
                "JWT plan type",
                FieldType.SELECT,
                required=False,
                condition=lambda values: values["plan_type"] == "JWT",
            ),
        ]

        def build_payload(self, form_data):
            return dict(form_data)

        def get_submit_endpoint(self, environment: str) -> str:
            return "https://example.invalid"

    monkeypatch.setattr(
        container.forms, "get_form", lambda _form_id: ConditionalForm()
    )

    hidden = container.forms.describe("test.legacy-condition", "test_int")
    jwt_field = next(
        field for field in hidden["fields"] if field["key"] == "plan_jwt_type"
    )
    assert jwt_field["visible"] is False
    assert "form condition failed" not in caplog.text

    visible = container.forms.state(
        "test.legacy-condition", "test_int", {"plan_type": "JWT"}
    )
    jwt_field = next(
        field for field in visible["fields"] if field["key"] == "plan_jwt_type"
    )
    assert jwt_field["visible"] is True


def test_large_reference_is_searched_server_side_and_keeps_selection(
    container: ApplicationContainer,
) -> None:
    document = container.forms.describe("other.ingress.enable", "test_int")
    api_field = next(field for field in document["fields"] if field["key"] == "apis")
    ingress_type = next(
        field for field in document["fields"] if field["key"] == "ingress_type"
    )

    # Exactly 100 APIs are intentionally not embedded in the form document.
    # Small dictionaries still render immediately without a second request.
    assert "options" not in api_field
    assert len(ingress_type["options"]) == 3

    selected_id = "550e8400-e29b-41d4-a716-446655440002"
    result = container.forms.options(
        "other.ingress.enable",
        "apis",
        "test_int",
        {"apis": selected_id},
        "no-result-for-this-query",
        0,
        50,
        False,
    )
    assert len(result["items"]) == 1
    assert {
        key: result["items"][0][key]
        for key in ("id", "name", "context_path")
    } == {
        "id": selected_id,
        "name": "service103",
        "context_path": "/api/v1/users/service103",
    }
    assert result["has_more"] is False


def test_global_search_uses_extension_catalog_configuration(
    container: ApplicationContainer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = ReferenceConfig(
        source="corp_search",
        resource="authoritative_apis",
        value_key="uuid",
        label_key="display_name",
        search_keys=("route", "display_name"),
    )

    class Resolver:
        calls: list[tuple[ReferenceConfig, str]] = []

        def resolve(self, config, environment="", extra_params=None):
            self.calls.append((config, environment))
            return [{
                "uuid": "api-42",
                "display_name": "Payments",
                "route": "/payments/v2",
            }]

    resolver = Resolver()
    monkeypatch.setattr(container, "search_catalogs", {"api": reference})
    monkeypatch.setattr(container, "new_reference_resolver", lambda: resolver)

    result = container.forms.search(
        "api", ["test_int"], "/PAYMENTS", limit=10, refresh=False
    )

    assert resolver.calls == [(reference, "test_int")]
    assert result == {
        "items": [{
            "environment": "test_int",
            "label": "Payments",
            "value": "api-42",
            "item": {
                "uuid": "api-42",
                "display_name": "Payments",
                "route": "/payments/v2",
            },
        }],
        "truncated": False,
    }


def test_global_search_reports_cache_timestamp_per_environment(
    container: ApplicationContainer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = ReferenceConfig(
        source="corp_search",
        resource="authoritative_apis",
        value_key="uuid",
        label_key="display_name",
        search_keys=("route",),
    )
    monkeypatch.setattr(container, "search_catalogs", {"api": reference})
    container.reference_cache.set(
        reference.resource,
        "test_int",
        [{"uuid": "api-42", "display_name": "Payments", "route": "/payments"}],
    )

    result = container.forms.search_cache_status(
        "api", ["test_int", "test_int", "prod_ext"]
    )

    assert [item["environment"] for item in result["items"]] == [
        "test_int", "prod_ext",
    ]
    assert isinstance(result["items"][0]["updated_at"], float)
    assert result["items"][1]["updated_at"] is None


def test_global_search_refresh_invalidates_and_reloads_selected_environments(
    container: ApplicationContainer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = ReferenceConfig(
        source="corp_search",
        resource="authoritative_apis",
        value_key="uuid",
        label_key="display_name",
        search_keys=("route",),
    )

    class Resolver:
        calls: list[str] = []

        def resolve(self, _config, environment="", extra_params=None):
            self.calls.append(environment)
            return [{"uuid": environment, "display_name": environment, "route": "/"}]

    resolver = Resolver()
    monkeypatch.setattr(container, "search_catalogs", {"api": reference})
    monkeypatch.setattr(container, "new_reference_resolver", lambda: resolver)
    container.reference_cache.set(reference.resource, "test_int", [{"old": True}])

    result = container.forms.refresh_search_catalog(
        "api", ["test_int", "prod_ext"]
    )

    assert resolver.calls == ["test_int", "prod_ext"]
    assert [item["count"] for item in result["items"]] == [1, 1]
    assert container.reference_cache.get_timestamp(
        reference.resource, "test_int"
    ) is None


class _ActionForm(BaseForm):
    @property
    def form_id(self) -> str:
        return "test.server-action"

    @property
    def title(self) -> str:
        return "Action"

    @property
    def category(self) -> str:
        return "other"

    @property
    def fields(self):
        return [FieldDefinition("name", "Name", FieldType.TEXT)]

    def build_payload(self, form_data):
        return dict(form_data)

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"

    def get_server_actions(self):
        return [ServerAction(
            "normalise",
            "Normalise",
            lambda _environment, values: {
                "message": "Done",
                "values": {"name": str(values["name"]).upper()},
            },
            confirmation_text="Run normalisation?",
        )]


class _SubmitHookForm(BaseForm):
    @property
    def form_id(self) -> str:
        return "test.submit-hooks"

    @property
    def title(self) -> str:
        return "Submit hooks"

    @property
    def category(self) -> str:
        return "other"

    @property
    def fields(self):
        return [FieldDefinition(
            "category",
            "Category",
            FieldType.SELECT,
            reference=ReferenceConfig(
                source="local",
                resource="api_categories.json",
                value_key="id",
                label_key="name",
            ),
            plural=True,
        )]

    def build_payload(self, form_data):
        return {"category": form_data["category"]}

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://submit.example.invalid/forms"

    def get_auth_type(self) -> str:
        return "none"

    def get_submit_headers(self, environment: str):
        return {"X-Environment": environment}

    def pre_submit(self, form_data, payload, environment):
        selected = self.screen.get_field_item("category")
        assert selected and selected["id"] == form_data["category"]
        second = self.screen.get_field_item("category_2")
        assert second and second["id"] == form_data["category_2"]
        payload["categoryLabel"] = selected["name"]


class _DependentReferenceForm(BaseForm):
    @property
    def form_id(self) -> str:
        return "test.dependent-reference"

    @property
    def title(self) -> str:
        return "Dependent reference"

    @property
    def category(self) -> str:
        return "other"

    @property
    def fields(self):
        return [
            FieldDefinition(
                "api",
                "API",
                FieldType.SELECT,
                reference=ReferenceConfig(
                    source="test",
                    resource="apis",
                    value_key="id",
                    label_key="name",
                ),
            ),
            FieldDefinition(
                "ingress",
                "Ingress",
                FieldType.SELECT,
                reference=ReferenceConfig(
                    source="test",
                    resource="ingresses",
                    value_key="id",
                    label_key="name",
                    required_params=("api",),
                ),
                depends_on="api",
                depends_on_field="context_path",
            ),
        ]

    def build_payload(self, form_data):
        return dict(form_data)

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"


class _DependentResolver:
    def __init__(self) -> None:
        self.calls = []

    def resolve(self, reference, environment, extra_params=None):  # noqa: ANN001
        self.calls.append((reference.resource, environment, extra_params))
        if reference.resource == "apis":
            return [{"id": "api-1", "name": "Orders", "context_path": "/orders"}]
        if extra_params == {"api": "/orders"}:
            return [{"id": "ingress-1", "name": "Internal"}]
        return []


class _CaptureHttpClient:
    def __init__(self) -> None:
        self.request = None

    def set_token(self, _token: str) -> None:
        return None

    def post(self, url, payload, headers=None):  # noqa: ANN001
        self.request = (url, payload, headers)
        return {"accepted": True}


def test_server_action_requires_one_time_confirmation(container: ApplicationContainer) -> None:
    registry = FormRegistry()
    registry.register(_ActionForm())
    try:
        form = container.forms.get_form("test.server-action")
        version = form_version(form)
        first = container.forms.run_action(
            form.form_id, "normalise", "test_int", {"name": "orders"}, version, ""
        )
        assert first["confirmation_required"] is True
        result = container.forms.run_action(
            form.form_id,
            "normalise",
            "test_int",
            {"name": "orders"},
            version,
            first["confirmation_token"],
        )
        assert result == {
            "success": True,
            "message": "Done",
            "values": {"name": "ORDERS"},
            "data": None,
        }
        repeated = container.forms.run_action(
            form.form_id,
            "normalise",
            "test_int",
            {"name": "orders"},
            version,
            first["confirmation_token"],
        )
        assert repeated["confirmation_required"] is True
    finally:
        registry.clear()
        register_all_forms()


def test_submit_uses_original_python_hooks_and_full_reference_item(
    container: ApplicationContainer,
) -> None:
    registry = FormRegistry()
    registry.register(_SubmitHookForm())
    capture = _CaptureHttpClient()
    original = container.new_submit_service
    container.new_submit_service = lambda: SubmitService(  # type: ignore[method-assign]
        capture, container.env_manager  # type: ignore[arg-type]
    )
    try:
        form = container.forms.get_form("test.submit-hooks")
        result = container.forms.submit(
            form.form_id,
            "test_int",
            {"category": "internal", "category_2": "external"},
            form_version(form),
            "",
        )
        assert result["success"] is True
        assert capture.request == (
            "https://submit.example.invalid/forms",
            {"category": "internal", "categoryLabel": "Внутреннее АПИ"},
            {"X-Environment": "test_int"},
        )
        assert container.run_storage.load_all()[0].form_id == form.form_id
    finally:
        container.new_submit_service = original  # type: ignore[method-assign]
        registry.clear()
        register_all_forms()


def test_dependent_reference_can_use_a_field_from_selected_parent_item(
    container: ApplicationContainer,
) -> None:
    registry = FormRegistry()
    registry.register(_DependentReferenceForm())
    resolver = _DependentResolver()
    original = container.new_reference_resolver
    container.new_reference_resolver = lambda: resolver  # type: ignore[method-assign]
    try:
        result = container.forms.options(
            "test.dependent-reference",
            "ingress",
            "test_int",
            {"api": "api-1"},
            "",
            0,
            100,
            False,
        )
        assert result["items"] == [{"id": "ingress-1", "name": "Internal"}]
        assert resolver.calls[-1] == (
            "ingresses",
            "test_int",
            {"api": "/orders"},
        )

        calls_before = len(resolver.calls)
        empty = container.forms.options(
            "test.dependent-reference",
            "ingress",
            "test_int",
            {},
            "",
            0,
            100,
            False,
        )
        assert empty["items"] == []
        assert len(resolver.calls) == calls_before
    finally:
        container.new_reference_resolver = original  # type: ignore[method-assign]
        registry.clear()
        register_all_forms()
