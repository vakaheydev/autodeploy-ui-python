from __future__ import annotations

from pathlib import Path

import pytest

from forms.base_form import (
    BaseForm,
    FormValidationIssue,
    ITSMFetchMode,
    ITSMFetchResult,
    ServerAction,
    ServerActionDialog,
    ServerDialogAction,
    ServerDialogActionResult,
)
from forms.fields import (
    FieldDefinition,
    FieldType,
    ReferenceConfig,
    ReferenceDependency,
)
from forms.loader import register_all_forms
from forms.registry import FormRegistry
from opencode_integration.data_sources import ITSMAIPrompt, ITSMAIPromptRequest
from webapp.container import ApplicationContainer
from webapp.extensions import RuntimeServices
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
    assert summary["description"] == "Создание и первичная настройка нового API в Gravitee."
    assert summary["description"] in summary["keywords"]
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
        container.forms,
        "get_form",
        lambda _form_id, _environment="": ConditionalForm(),
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


def test_nested_condition_uses_checkbox_default_on_initial_projection(
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConditionalBlockForm(BaseForm):
        form_id = "test.conditional-block"
        title = "Conditional block"
        category = "other"
        fields = [FieldDefinition(
            "settings",
            "Settings",
            FieldType.BLOCK,
            required=False,
            block_fields=[
                FieldDefinition(
                    "disabled",
                    "Disabled",
                    FieldType.CHECKBOX,
                    required=False,
                ),
                FieldDefinition(
                    "catalog_item",
                    "Catalog item",
                    FieldType.SELECT,
                    required=False,
                    reference=ReferenceConfig(
                        source="corp_http",
                        resource="catalog",
                        value_key="id",
                        label_key="name",
                    ),
                    condition=lambda values: values["disabled"] is False,
                ),
            ],
        )]

        def build_payload(self, form_data):
            return dict(form_data)

        def get_submit_endpoint(self, environment: str) -> str:
            return "https://example.invalid"

    monkeypatch.setattr(
        container.forms,
        "get_form",
        lambda _form_id, _environment="": ConditionalBlockForm(),
    )

    initial = container.forms.describe("test.conditional-block", "test_int")
    settings = initial["fields"][0]
    catalog = next(
        field for field in settings["fields"] if field["key"] == "catalog_item"
    )

    assert initial["initial_values"] == {"settings": {"disabled": False}}
    assert catalog["visible"] is True

    toggled = container.forms.state(
        "test.conditional-block",
        "test_int",
        {"settings": {"disabled": True}},
        initial["version"],
    )
    toggled_catalog = next(
        field
        for field in toggled["fields"][0]["fields"]
        if field["key"] == "catalog_item"
    )
    assert toggled_catalog["visible"] is False


def test_repeated_blocks_project_conditions_for_each_instance(
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RepeatedConditionalBlockForm(BaseForm):
        form_id = "test.repeated-conditional-block"
        title = "Repeated conditional block"
        category = "other"
        fields = [FieldDefinition(
            "plan",
            "План",
            FieldType.BLOCK,
            required=False,
            plural=True,
            plural_max=3,
            block_fields=[
                FieldDefinition("type", "Тип", FieldType.TEXT),
                FieldDefinition(
                    "jwt_secret",
                    "JWT secret",
                    FieldType.TEXT,
                    required=False,
                    condition=lambda values: values.get("type") == "JWT",
                ),
                FieldDefinition(
                    "api_key",
                    "API key",
                    FieldType.TEXT,
                    required=False,
                    condition=lambda values: values.get("type") == "API_KEY",
                ),
            ],
        )]

        def build_payload(self, form_data):
            return dict(form_data)

        def get_submit_endpoint(self, environment: str) -> str:
            return "https://example.invalid"

    monkeypatch.setattr(
        container.forms,
        "get_form",
        lambda _form_id, _environment="": RepeatedConditionalBlockForm(),
    )

    document = container.forms.describe(
        "test.repeated-conditional-block",
        "test_int",
        {
            "plan": {"type": "JWT", "jwt_secret": "first"},
            "plan_2": {"type": "API_KEY", "api_key": "second"},
        },
    )
    block = document["fields"][0]
    first = {field["key"]: field for field in block["fields"]}
    second = {field["key"]: field for field in block["instances"]["plan_2"]}

    assert first["jwt_secret"]["visible"] is True
    assert first["api_key"]["visible"] is False
    assert second["jwt_secret"]["visible"] is False
    assert second["api_key"]["visible"] is True
    assert second["api_key"]["path"] == "plan_2.api_key"
    resolved, _siblings = container.forms._find_field_context(
        RepeatedConditionalBlockForm.fields,
        "plan_2.api_key",
    )
    assert resolved.key == "api_key"


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
            self._normalise,
            confirmation_text="Run normalisation?",
        )]

    def _normalise(self, environment, values):
        assert self.current_environment == environment
        assert self.screen.current_environment == environment
        assert self.apply_form_data({
            "name": str(values["name"]).upper(),
            "unknown": "ignored like the Tkinter screen",
        }) == ["name"]
        return {"message": "Done"}


class _DialogActionForm(BaseForm):
    form_id = "test.dialog-action"
    title = "Dialog action"
    category = "other"
    fields = [FieldDefinition("name", "Name", FieldType.TEXT)]

    def build_payload(self, form_data):
        return dict(form_data)

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"

    def get_server_actions(self):
        dialog = ServerActionDialog(
            title="Выбрать методы из Swagger",
            description="Источники и действия принадлежат Python-форме.",
            fields=(
                FieldDefinition(
                    "api",
                    "API",
                    FieldType.SELECT,
                    reference=ReferenceConfig(
                        source="test",
                        resource="apis",
                        value_key="id",
                        label_key="name",
                        search_keys=("name", "context_path"),
                    ),
                ),
                FieldDefinition(
                    "swagger_environment",
                    "Окружение Swagger",
                    FieldType.TEXT,
                ),
                FieldDefinition(
                    "swagger_file",
                    "Swagger file",
                    FieldType.FILE,
                    required=False,
                    file_type=".json",
                ),
                FieldDefinition(
                    "methods",
                    "Методы",
                    FieldType.MULTISELECT,
                    reference=ReferenceConfig(
                        source="test",
                        resource="swagger_methods",
                        value_key="id",
                        label_key="label",
                        required_params=(
                            "api_path",
                            "swagger_environment",
                            "form_name",
                        ),
                    ),
                    reference_dependencies=(
                        ReferenceDependency(
                            "api",
                            parameter="api_path",
                            item_field="context_path",
                        ),
                        ReferenceDependency("swagger_environment"),
                        ReferenceDependency(
                            "swagger_file",
                            parameter="swagger_document",
                        ),
                        ReferenceDependency(
                            "name",
                            parameter="form_name",
                            scope="form",
                        ),
                    ),
                ),
                FieldDefinition(
                    "status",
                    "Статус",
                    FieldType.TEXT,
                    required=False,
                ),
            ),
            actions=(
                ServerDialogAction(
                    "inspect",
                    "Проверить",
                    self._inspect,
                    require_valid_dialog=False,
                    close_on_success=False,
                ),
                ServerDialogAction("apply", "Применить", self._apply),
            ),
            initial_values=self._initial_dialog_values,
            validate=self._validate_dialog,
        )
        return [ServerAction(
            action_id="choose_methods",
            label="Выбрать методы из Swagger",
            dialog=dialog,
        )]

    @staticmethod
    def _initial_dialog_values(environment, form_values):
        return {
            "swagger_environment": environment,
            "status": f"Для {form_values.get('name', '')}",
        }

    @staticmethod
    def _validate_dialog(_environment, _form_values, dialog_values):
        if not dialog_values.get("methods"):
            return [FormValidationIssue("methods", "Выберите хотя бы один метод")]
        return []

    @staticmethod
    def _inspect(_environment, _form_values, _dialog_values):
        return ServerDialogActionResult(
            message="Swagger прочитан",
            dialog_values={"status": "Готово к применению"},
        )

    def _apply(self, environment, form_values, dialog_values):
        assert self.current_environment == environment
        assert self.screen.get_field_item("api")["id"] == dialog_values["api"]
        return ServerDialogActionResult(
            message="Методы перенесены",
            form_values={
                "name": f"{form_values['name']}:{','.join(dialog_values['methods'])}"
            },
        )


class _ConditionalPatchForm(BaseForm):
    form_id = "test.conditional-patch"
    title = "Conditional patch"
    category = "other"
    fields = [
        FieldDefinition(
            "create_application",
            "Create application",
            FieldType.CHECKBOX,
            default=False,
        ),
        FieldDefinition(
            "application_name",
            "Application name",
            FieldType.TEXT,
            # Compatibility case from legacy corporate forms: False meant
            # "there is no value while the field is hidden".
            default=False,
            condition=lambda values: values["create_application"] is True,
        ),
    ]

    def build_payload(self, form_data):
        return dict(form_data)

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"

    def get_server_actions(self):
        return [ServerAction(
            "fill",
            "Fill",
            lambda _environment, _values: {
                "values": {
                    "create_application": True,
                    "application_name": False,
                },
            },
        )]


class _TicketPatchForm(BaseForm):
    form_id = "test.ticket-patch"
    title = "Ticket patch"
    category = "other"
    fields = [
        FieldDefinition("name", "Name", FieldType.TEXT),
        FieldDefinition("owner", "Owner", FieldType.TEXT),
    ]
    itsm_support = True

    def build_payload(self, form_data):
        return dict(form_data)

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"

    def fetch_from_itsm(self, environment: str, ticket_id: str):
        assert ticket_id == "REQ-42"
        assert self.current_environment == environment
        assert self.screen.current_environment == environment
        assert self.screen.apply_form_data({"name": "From ITSM"}) == ["name"]
        assert self.apply_form_data({"owner": "Platform", "ignored": True}) == [
            "owner"
        ]
        return None


class _AITicketForm(BaseForm):
    form_id = "test.ticket-ai"
    title = "Ticket AI"
    category = "other"
    fields = [FieldDefinition("name", "Name", FieldType.TEXT)]
    itsm_support = True

    def build_payload(self, form_data):
        return dict(form_data)

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"

    def fetch_from_itsm(self, environment: str, ticket_id: str):
        return ITSMFetchResult.ai(
            {
                "summary": f"Create from {ticket_id}",
                "access_token": "must-not-reach-opencode",
            },
            instruction="Use the request summary",
        )


class _EnvironmentAwareForm(BaseForm):
    form_id = "test.environment-aware"
    title = "Environment aware"
    category = "other"
    fields = [FieldDefinition("name", "Name", FieldType.TEXT)]

    def validate(self, form_data):
        if self.current_environment != "prod_ext":
            return ["Текущее окружение не передано в форму"]
        return super().validate(form_data)

    def build_payload(self, form_data):
        return {
            **form_data,
            "environment": self.current_environment,
        }

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"


class _InlineValidationForm(BaseForm):
    form_id = "test.inline-validation"
    title = "Inline validation"
    category = "other"
    fields = [
        FieldDefinition("owner", "Владелец", FieldType.TEXT, required=False),
        FieldDefinition(
            "ingresses", "Ингрессы", FieldType.MULTISELECT, required=False
        ),
    ]

    def validate(self, form_data):
        return [
            'Поле "Владелец" содержит некорректное значение',
            self.validation_error(
                "ingresses",
                "Необходимо выбрать хотя бы один ingress",
            ),
        ]

    def build_payload(self, form_data):
        return dict(form_data)

    def get_submit_endpoint(self, environment: str) -> str:
        return "https://example.invalid"


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


def test_server_action_dialog_reuses_fields_and_passes_multiple_dependencies(
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Resolver:
        def __init__(self) -> None:
            self.method_params = []

        def resolve(self, reference, environment="", extra_params=None):
            assert environment == "test_int"
            if reference.resource == "apis":
                return [{
                    "id": "api-1",
                    "name": "Orders",
                    "context_path": "/orders",
                }]
            if reference.resource == "swagger_methods":
                self.method_params.append(extra_params)
                if extra_params == {
                    "api_path": "/orders",
                    "swagger_environment": "test_int",
                    "swagger_document": '{"openapi":"3.0.0"}',
                    "form_name": "Subscription",
                }:
                    return [
                        {"id": "GET /orders", "label": "GET /orders"},
                        {"id": "POST /orders", "label": "POST /orders"},
                    ]
            return []

    registry = FormRegistry()
    registry.register(_DialogActionForm())
    resolver = Resolver()
    monkeypatch.setattr(container, "new_reference_resolver", lambda: resolver)
    try:
        document = container.forms.describe(
            "test.dialog-action",
            "test_int",
            {"name": "Subscription"},
        )
        descriptor = document["custom_actions"][0]
        assert descriptor["dialog"] is True
        version = document["version"]

        opened = container.forms.open_action_dialog(
            "test.dialog-action",
            "choose_methods",
            "test_int",
            {"name": "Subscription"},
            version,
        )
        assert opened["success"] is True
        assert opened["title"] == "Выбрать методы из Swagger"
        assert opened["values"] == {
            "swagger_environment": "test_int",
            "status": "Для Subscription",
        }
        methods = next(field for field in opened["fields"] if field["key"] == "methods")
        assert methods["reference"]["endpoint"].endswith(
            "/actions/choose_methods/dialog/fields/methods/options"
        )
        assert methods["reference_dependencies"] == [
            {"field": "api", "parameter": "api_path", "item_field": "context_path", "scope": "current"},
            {"field": "swagger_environment", "parameter": "swagger_environment", "item_field": None, "scope": "current"},
            {"field": "swagger_file", "parameter": "swagger_document", "item_field": None, "scope": "current"},
            {"field": "name", "parameter": "form_name", "item_field": None, "scope": "form"},
        ]

        dialog_values = {
            "api": "api-1",
            "swagger_environment": "test_int",
            "swagger_file": '{"openapi":"3.0.0"}',
            "methods": ["GET /orders"],
            "status": "",
        }
        options = container.forms.action_dialog_options(
            "test.dialog-action",
            "choose_methods",
            "methods",
            "test_int",
            {
                "name": "Subscription",
                "browser_only_form_parameter": "must-not-reach-handler",
            },
            {
                **dialog_values,
                "browser_only_parameter": "must-not-reach-handler",
            },
            version,
            "GET",
            0,
            50,
            False,
        )
        assert options["items"] == [{
            "id": "GET /orders",
            "label": "GET /orders",
        }]
        assert resolver.method_params[-1] == {
            "api_path": "/orders",
            "swagger_environment": "test_int",
            "swagger_document": '{"openapi":"3.0.0"}',
            "form_name": "Subscription",
        }

        invalid = container.forms.run_action_dialog_button(
            "test.dialog-action",
            "choose_methods",
            "apply",
            "test_int",
            {"name": "Subscription"},
            {**dialog_values, "methods": []},
            version,
        )
        assert invalid["success"] is False
        assert invalid["validation_scope"] == "dialog"
        assert invalid["validation"]["errors"][-1]["field"] == "methods"

        inspected = container.forms.run_action_dialog_button(
            "test.dialog-action",
            "choose_methods",
            "inspect",
            "test_int",
            {"name": "Subscription"},
            dialog_values,
            version,
        )
        assert inspected["close_dialog"] is False
        assert inspected["values"]["status"] == "Готово к применению"

        applied = container.forms.run_action_dialog_button(
            "test.dialog-action",
            "choose_methods",
            "apply",
            "test_int",
            {"name": "Subscription"},
            dialog_values,
            version,
        )
        assert applied["success"] is True
        assert applied["close_dialog"] is True
        assert applied["form_values"] == {
            "name": "Subscription:GET /orders",
        }
    finally:
        registry.clear()
        register_all_forms()


def test_boolean_empty_marker_never_populates_conditional_text_field(
    container: ApplicationContainer,
) -> None:
    registry = FormRegistry()
    registry.register(_ConditionalPatchForm())
    try:
        form = container.forms.get_form("test.conditional-patch", "test_int")
        version = form_version(form)

        initial = container.forms.describe(form.form_id, "test_int")
        conditional = next(
            field for field in initial["fields"]
            if field["key"] == "application_name"
        )
        assert initial["initial_values"] == {"create_application": False}
        assert conditional["visible"] is False
        assert conditional["default"] is None

        enabled = container.forms.state(
            form.form_id,
            "test_int",
            {"create_application": True},
            version,
        )
        conditional = next(
            field for field in enabled["fields"]
            if field["key"] == "application_name"
        )
        assert conditional["visible"] is True
        assert "application_name" not in enabled["initial_values"]

        action = container.forms.run_action(
            form.form_id,
            "fill",
            "test_int",
            {"create_application": False},
            version,
            "",
        )
        assert action["values"] == {"create_application": True}

        validation = container.forms.validate(
            form.form_id,
            "test_int",
            {"create_application": True, "application_name": False},
            version,
            validate_references=False,
        )
        assert "application_name" not in validation.values
        assert any(
            error["field"] == "application_name"
            and error["code"] == "invalid_type"
            for error in validation.errors
        )
    finally:
        registry.clear()
        register_all_forms()


def test_ticket_hook_can_apply_a_headless_form_patch(
    container: ApplicationContainer,
) -> None:
    registry = FormRegistry()
    registry.register(_TicketPatchForm())
    try:
        result = container.forms.fetch_ticket(
            "test.ticket-patch", "regress_ext", "REQ-42"
        )
        assert result == {
            "mode": "deterministic",
            "values": {"name": "From ITSM", "owner": "Platform"},
            "errors": [],
            "valid": True,
        }
        assert (
            container.forms.get_form(
                "test.ticket-patch", "regress_ext"
            ).current_environment
            == "regress_ext"
        )
    finally:
        registry.clear()
        register_all_forms()


def test_typed_itsm_result_enforces_mode_specific_payloads() -> None:
    deterministic = ITSMFetchResult.deterministic({"name": "Payments"})
    assert deterministic.mode is ITSMFetchMode.DETERMINISTIC
    assert deterministic.values == {"name": "Payments"}

    ai = ITSMFetchResult.ai({"summary": "Create API"}, instruction="Map fields")
    assert ai.mode is ITSMFetchMode.AI
    assert ai.context == {"summary": "Create API"}

    with pytest.raises(ValueError, match="context"):
        ITSMFetchResult(mode=ITSMFetchMode.AI)
    with pytest.raises(ValueError, match="values"):
        ITSMFetchResult(
            mode=ITSMFetchMode.AI,
            values={"name": "mixed"},
            context={"summary": "mixed"},
        )


def test_ai_itsm_mode_delegates_sanitized_context_to_exact_form(
    container: ApplicationContainer,
) -> None:
    class FakeAI:
        def __init__(self) -> None:
            self.arguments = None

        def start_form_ticket_fill(self, **kwargs):
            self.arguments = kwargs
            return {
                "mode": "ai",
                "draft_id": "draft-1",
                "workflow_id": "workflow-1",
                "job_id": "job-1",
                "status": "running",
                "progress": "Copilot анализирует…",
            }

    registry = FormRegistry()
    registry.register(_AITicketForm())
    fake_ai = FakeAI()
    container.ai = fake_ai
    original_service_provider = container.service_provider

    class PromptITSM:
        request: ITSMAIPromptRequest | None = None

        def get_ai_prompt(self, request: ITSMAIPromptRequest) -> ITSMAIPrompt:
            self.request = request
            return ITSMAIPrompt(
                ticket_type="create_api_v2",
                instructions="Use summary as the proposed API name.",
            )

    prompt_itsm = PromptITSM()
    container.itsm_prompt_settings.update([{
        "ticket_type": "create_api_v2",
        "prompt": "Use the operator-managed API mapping.",
    }])

    def prompt_services(env_manager, http_client):
        services = original_service_provider(env_manager, http_client)
        return RuntimeServices(
            itsm=prompt_itsm,
            tfs=services.tfs,
            gravitee=services.gravitee,
        )

    container.service_provider = prompt_services
    try:
        version = form_version(container.forms.get_form("test.ticket-ai", "test_int"))
        result = container.forms.fetch_ticket(
            "test.ticket-ai",
            "test_int",
            "REQ-42",
            {"name": "Existing"},
            version,
        )

        assert result["mode"] == "ai"
        assert result["draft_id"] == "draft-1"
        assert fake_ai.arguments is not None
        assert fake_ai.arguments["form_id"] == "test.ticket-ai"
        assert fake_ai.arguments["environment"] == "test_int"
        assert fake_ai.arguments["current_values"] == {"name": "Existing"}
        assert fake_ai.arguments["ticket_type"] == "create_api_v2"
        assert fake_ai.arguments["instruction"] == (
            "Use the operator-managed API mapping.\n\n"
            "Use the request summary"
        )
        assert fake_ai.arguments["source_context"] == {
            "summary": "Create from REQ-42",
            "access_token": "[REDACTED]",
        }
        assert prompt_itsm.request is not None
        assert prompt_itsm.request.form_id == "test.ticket-ai"
        assert prompt_itsm.request.ticket_context == {
            "summary": "Create from REQ-42",
            "access_token": "[REDACTED]",
        }
    finally:
        container.ai = None
        container.service_provider = original_service_provider
        registry.clear()
        register_all_forms()


def test_current_environment_is_available_to_validation_and_payload_hooks(
    container: ApplicationContainer,
) -> None:
    registry = FormRegistry()
    registry.register(_EnvironmentAwareForm())
    try:
        form = container.forms.get_form("test.environment-aware", "prod_ext")
        preview = container.forms.preview(
            form.form_id,
            "prod_ext",
            {"name": "Orders"},
            form_version(form),
        )
        assert preview["valid"] is True
        assert preview["payload"] == {
            "name": "Orders",
            "environment": "prod_ext",
        }
    finally:
        registry.clear()
        register_all_forms()


def test_domain_validation_errors_are_attached_to_their_fields(
    container: ApplicationContainer,
) -> None:
    registry = FormRegistry()
    registry.register(_InlineValidationForm())
    try:
        form = container.forms.get_form("test.inline-validation", "test_int")
        validation = container.forms.validate(
            form.form_id,
            "test_int",
            {"owner": "unknown", "ingresses": []},
            form_version(form),
        )
        assert [(item["field"], item["message"]) for item in validation.errors] == [
            ("owner", 'Поле "Владелец" содержит некорректное значение'),
            ("ingresses", "Необходимо выбрать хотя бы один ingress"),
        ]
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
