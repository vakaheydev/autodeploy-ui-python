"""Headless runtime over the existing Python form contracts.

The module deliberately calls the original ``validate``, ``build_payload``,
``pre_submit`` and result hooks.  React receives only a JSON projection and is
never a second source of business rules.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from config.categories import CATEGORIES
from config.environments import ENVIRONMENT_MAP
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
from forms.registry import FormRegistry
from opencode_integration.context_builder import (
    MAX_ITSM_AI_INSTRUCTIONS_CHARS,
    is_secret_key,
    redact_text,
    resolve_itsm_ai_prompt,
    sanitize,
)


_log = logging.getLogger("web.forms")
_PLURAL_RE = re.compile(r"^(.+)_(\d+)$")
_ACTION_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_INLINE_REFERENCE_MAX_ITEMS = 99
_INLINE_REFERENCE_MAX_BYTES = 64 * 1024
_STRING_FIELD_TYPES = {
    FieldType.TEXT,
    FieldType.TEXTAREA,
    FieldType.FILE,
    FieldType.SELECT,
}


class FormNotFoundError(KeyError):
    pass


class FormVersionConflict(ValueError):
    pass


class FormAIUnavailableError(RuntimeError):
    pass


class _ConditionValues(dict[str, Any]):
    """Legacy-compatible condition values where an unfilled field is ``None``."""

    def __missing__(self, _key: str) -> None:
        return None


@dataclass(frozen=True)
class RuntimeValidation:
    valid: bool
    values: dict[str, Any]
    errors: tuple[dict[str, Any], ...]
    visible_fields: tuple[str, ...]


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _condition_identity(condition: Any) -> str:
    if condition is None:
        return ""
    code = getattr(condition, "__code__", None)
    if code is not None:
        return hashlib.sha256(
            code.co_code + repr(code.co_consts).encode("utf-8", errors="replace")
        ).hexdigest()[:16]
    return f"{type(condition).__module__}.{type(condition).__qualname__}"


def _field_shape(field: FieldDefinition) -> dict[str, Any]:
    reference = field.reference
    return {
        "key": field.key,
        "label": field.label,
        "type": field.field_type.value,
        "required": field.required,
        "placeholder": field.placeholder,
        "default": _json_safe(field.default),
        "hint": field.hint,
        "file_type": field.file_type,
        "plural": field.plural,
        "plural_max": field.plural_max,
        "depends_on": field.depends_on,
        "depends_on_field": field.depends_on_field,
        "reference_dependencies": [
            {
                "field": item.field,
                "parameter": item.parameter,
                "item_field": item.item_field,
                "scope": item.scope,
            }
            for item in field.reference_dependencies
        ],
        "condition": _condition_identity(field.condition),
        "reference": (
            {
                "source": reference.source,
                "resource": reference.resource,
                "value_key": reference.value_key,
                "label_key": reference.label_key,
                "search_keys": list(reference.search_keys),
                "detail_keys": list(reference.detail_keys),
                "required_params": list(reference.required_params),
            }
            if reference
            else None
        ),
        "fields": [_field_shape(item) for item in field.block_fields],
    }


def form_version(form: BaseForm) -> str:
    payload = json.dumps(
        {
            "id": form.form_id,
            "title": form.title,
            "category": form.category,
            "fields": [_field_shape(field) for field in form.fields],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _visible(field: FieldDefinition, values: Mapping[str, Any]) -> bool:
    if field.condition is None:
        return True
    try:
        return bool(field.condition(_ConditionValues(values)))
    except Exception:
        _log.exception("form condition failed field=%s", field.key)
        return False


def _declared_default(field: FieldDefinition) -> Any:
    """Return a default that is compatible with the field's runtime type.

    Some legacy forms used ``False`` as an "empty" marker for values that are
    shown only after another checkbox is enabled.  Tkinter treated that marker
    as an empty text value, while the web client received a JSON boolean and
    rendered the literal word ``false``.  A boolean is a value only for a
    checkbox; for every other field it means that no usable default was
    declared.
    """
    if isinstance(field.default, bool) and field.field_type != FieldType.CHECKBOX:
        return None
    return field.default


def _public_item(item: Mapping[str, Any], reference: ReferenceConfig) -> dict[str, Any]:
    keys: list[str] = [reference.value_key, reference.label_key]
    keys.extend(reference.search_keys)
    keys.extend(reference.detail_keys)
    if not reference.detail_keys:
        keys.extend(str(key) for key in item.keys())
    result: dict[str, Any] = {}
    for key in dict.fromkeys(keys):
        if is_secret_key(key):
            continue
        if key in item:
            result[key] = _json_safe(item[key])
    return result


class _WebFormContext:
    """Compatibility replacement for ``FormScreen`` inside server hooks."""

    def __init__(
        self,
        selected: Optional[Mapping[str, list[dict[str, Any]]]] = None,
        *,
        environment: str = "",
        writable_fields: Optional[Iterable[FieldDefinition]] = None,
        selected_loader: Optional[
            Callable[[], Mapping[str, list[dict[str, Any]]]]
        ] = None,
    ) -> None:
        self.current_environment = environment
        self._selected = dict(selected or {})
        self._selected_loader = selected_loader
        self._selection_loaded = selected_loader is None
        self._writable_fields = (
            {field.key: field for field in writable_fields}
            if writable_fields is not None
            else None
        )
        self._applied: dict[str, Any] = {}

    def _selection(self) -> Mapping[str, list[dict[str, Any]]]:
        if not self._selection_loaded and self._selected_loader is not None:
            self._selected = dict(self._selected_loader())
            self._selection_loaded = True
        return self._selected

    def get_field_item(self, key: str) -> Optional[dict[str, Any]]:
        values = self._selection().get(key, [])
        return copy.deepcopy(values[0]) if values else None

    def get_field_items(self, key: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self._selection().get(key, []))

    def apply_form_data(self, data: Mapping[str, Any]) -> list[str]:
        if self._writable_fields is None:
            raise RuntimeError(
                "apply_form_data недоступен во время validate/build_payload/submit"
            )
        if not isinstance(data, Mapping):
            raise TypeError("apply_form_data ожидает mapping field_key -> value")
        applied: list[str] = []
        for raw_key, value in data.items():
            key = str(raw_key)
            field = self._writable_fields.get(key)
            if field is None:
                match = _PLURAL_RE.match(key)
                if match is not None:
                    candidate = self._writable_fields.get(match.group(1))
                    field = candidate if candidate is not None and candidate.plural else None
            if field is None:
                continue
            self._applied[key] = copy.deepcopy(value)
            applied.append(key)
        return applied

    @property
    def applied_values(self) -> dict[str, Any]:
        return copy.deepcopy(self._applied)


class FormRuntime:
    def __init__(self, container: Any) -> None:
        self.container = container

    def get_form(self, form_id: str, environment: str = "") -> BaseForm:
        try:
            source = FormRegistry().get(form_id)
        except KeyError as exc:
            raise FormNotFoundError(form_id) from exc
        form = copy.copy(source)
        client = self.container.new_http_client()
        services = self.container.service_provider(self.container.env_manager, client)
        form.tfs_service = services.tfs
        form.itsm_service = services.itsm
        form.gravitee_service = services.gravitee
        form.screen = None
        form.current_environment = str(environment)
        return form

    @staticmethod
    def _validate_server_actions(
        actions: Iterable[ServerAction],
        form_fields: Iterable[FieldDefinition] = (),
    ) -> None:
        values = tuple(actions)
        owning_fields = tuple(form_fields)
        if not all(isinstance(action, ServerAction) for action in values):
            raise TypeError("get_server_actions должен возвращать ServerAction")
        identifiers = [str(action.action_id) for action in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("ServerAction должны иметь уникальные action_id")
        for action in values:
            if not _ACTION_ID_RE.fullmatch(str(action.action_id)):
                raise ValueError(
                    f"Некорректный ServerAction action_id {action.action_id!r}"
                )
            if not str(action.label).strip():
                raise ValueError("ServerAction label не может быть пустым")
            has_handler = callable(action.handler)
            has_dialog = action.dialog is not None
            if has_handler == has_dialog:
                raise ValueError(
                    f"ServerAction {action.action_id!r} должен объявлять ровно "
                    "один handler или dialog"
                )
            if action.dialog is None:
                continue
            if action.confirmation_text:
                raise ValueError(
                    f"ServerAction {action.action_id!r} с dialog должен задавать "
                    "confirmation_text у конкретной кнопки диалога"
                )
            dialog = action.dialog
            if not str(dialog.title).strip():
                raise ValueError(
                    f"Диалог ServerAction {action.action_id!r} должен иметь title"
                )
            if not isinstance(dialog.initial_values, Mapping) and not callable(
                dialog.initial_values
            ):
                raise TypeError("ServerActionDialog.initial_values должен быть mapping или callable")
            if dialog.validate is not None and not callable(dialog.validate):
                raise TypeError("ServerActionDialog.validate должен быть callable или None")
            if not all(isinstance(field, FieldDefinition) for field in dialog.fields):
                raise TypeError("ServerActionDialog.fields должен содержать FieldDefinition")
            field_keys = [field.key for field in dialog.fields]
            if len(field_keys) != len(set(field_keys)):
                raise ValueError("Поля ServerActionDialog должны иметь уникальные key")
            FormRuntime._validate_reference_dependencies(
                dialog.fields,
                scope=f"ServerActionDialog {action.action_id!r}",
                form_fields=owning_fields,
                allow_form_scope=True,
            )
            if not dialog.actions:
                raise ValueError("ServerActionDialog должен содержать хотя бы одну кнопку")
            if not all(isinstance(item, ServerDialogAction) for item in dialog.actions):
                raise TypeError("ServerActionDialog.actions должен содержать ServerDialogAction")
            dialog_ids = [item.action_id for item in dialog.actions]
            if len(dialog_ids) != len(set(dialog_ids)):
                raise ValueError("Кнопки ServerActionDialog должны иметь уникальные action_id")
            for item in dialog.actions:
                if not _ACTION_ID_RE.fullmatch(str(item.action_id)):
                    raise ValueError(
                        f"Некорректный action_id кнопки диалога {item.action_id!r}"
                    )
                if not str(item.label).strip() or not callable(item.handler):
                    raise TypeError(
                        "Каждая кнопка ServerActionDialog должна иметь label и handler"
                    )

    @staticmethod
    def _validate_reference_dependencies(
        fields: Iterable[FieldDefinition],
        *,
        scope: str,
        form_fields: Iterable[FieldDefinition] = (),
        allow_form_scope: bool = False,
    ) -> None:
        """Fail early for ambiguous or unusable multi-input references."""
        siblings = tuple(fields)
        sibling_keys = {field.key for field in siblings}
        owning_fields = tuple(form_fields)
        form_keys = {field.key for field in owning_fields}
        for field in siblings:
            dependencies = tuple(field.reference_dependencies)
            if dependencies and field.reference is None:
                raise ValueError(
                    f"{scope}: поле {field.key!r} объявляет зависимости без reference"
                )
            if not all(
                isinstance(item, ReferenceDependency) for item in dependencies
            ):
                raise TypeError(
                    f"{scope}: reference_dependencies поля {field.key!r} "
                    "должен содержать ReferenceDependency"
                )
            parameters: set[str] = (
                {field.depends_on} if field.depends_on else set()
            )
            for dependency in dependencies:
                parameter = dependency.parameter or dependency.field
                dependency_scope = str(dependency.scope or "current").strip().casefold()
                if dependency_scope not in {"current", "form"}:
                    raise ValueError(
                        f"{scope}: scope зависимости {dependency.field!r} поля "
                        f"{field.key!r} должен быть 'current' или 'form'"
                    )
                if dependency_scope == "form" and not allow_form_scope:
                    raise ValueError(
                        f"{scope}: scope='form' разрешён только для полей "
                        "ServerActionDialog"
                    )
                source_keys = form_keys if dependency_scope == "form" else sibling_keys
                source_fields = owning_fields if dependency_scope == "form" else siblings
                if dependency.field not in source_keys:
                    raise ValueError(
                        f"{scope}: зависимость {dependency.field!r} поля "
                        f"{field.key!r} отсутствует в scope={dependency_scope!r}"
                    )
                if dependency_scope == "current" and dependency.field == field.key:
                    raise ValueError(
                        f"{scope}: поле {field.key!r} не может зависеть от себя"
                    )
                if not str(parameter).strip():
                    raise ValueError(
                        f"{scope}: параметр зависимости поля {field.key!r} пуст"
                    )
                repeats_legacy = (
                    dependency.field == field.depends_on
                    and parameter == field.depends_on
                )
                if parameter in parameters and not repeats_legacy:
                    raise ValueError(
                        f"{scope}: параметр зависимости {parameter!r} поля "
                        f"{field.key!r} объявлен несколько раз"
                    )
                parameters.add(parameter)
                if dependency.item_field:
                    parent = next(
                        item for item in source_fields
                        if item.key == dependency.field
                    )
                    if parent.reference is None:
                        raise ValueError(
                            f"{scope}: item_field зависимости "
                            f"{dependency.field!r} требует reference у поля-источника"
                        )
            if field.reference is not None:
                missing = set(field.reference.required_params) - parameters
                if dependencies and missing:
                    raise ValueError(
                        f"{scope}: для поля {field.key!r} не объявлены зависимости "
                        "required_params: " + ", ".join(sorted(missing))
                    )
            if field.field_type == FieldType.BLOCK:
                FormRuntime._validate_reference_dependencies(
                    field.block_fields,
                    scope=f"{scope}.{field.key}",
                    form_fields=owning_fields,
                    allow_form_scope=allow_form_scope,
                )

    def _server_action(self, form: BaseForm, action_id: str) -> ServerAction:
        actions = tuple(form.get_server_actions())
        self._validate_server_actions(actions, form.fields)
        action = next(
            (item for item in actions if item.action_id == action_id),
            None,
        )
        if action is None:
            raise FormNotFoundError(action_id)
        return action

    def list_forms(self, category: str = "") -> list[dict[str, Any]]:
        forms = FormRegistry().all_forms()
        if category:
            forms = [form for form in forms if form.category == category]
        return [
            {
                "id": form.form_id,
                "title": form.title,
                "category": form.category,
                "category_label": CATEGORIES.get(form.category, form.category),
                "description": str(form.description or "").strip(),
                "version": form_version(form),
                "field_count": len(form.fields),
                "confirm_submit": form.confirm_submit(),
                "itsm_support": form.itsm_support,
                "keywords": self._form_keywords(form),
            }
            for form in sorted(forms, key=lambda value: (value.category, value.title))
        ]

    @staticmethod
    def _form_keywords(form: BaseForm) -> list[str]:
        """Searchable public vocabulary without loading reference values."""
        values = [
            form.form_id,
            form.title,
            form.description,
            form.category,
            CATEGORIES.get(form.category, ""),
        ]

        def collect(fields: Iterable[FieldDefinition]) -> None:
            for field in fields:
                values.extend((field.key, field.label, field.hint, field.placeholder))
                collect(field.block_fields)

        collect(form.fields)
        return list(dict.fromkeys(
            text.strip() for value in values
            if (text := str(value or "").strip())
        ))

    def describe(
        self, form_id: str, environment: str, values: Optional[Mapping[str, Any]] = None
    ) -> dict[str, Any]:
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        current = self._with_defaults(form.fields, dict(values or {}))
        actions = tuple(form.get_server_actions())
        self._validate_server_actions(actions, form.fields)
        fields = [
            self._field_document(
                form, field, environment, current, siblings=form.fields
            )
            for field in form.fields
        ]
        version = form_version(form)
        return {
            "id": form.form_id,
            "title": form.title,
            "category": form.category,
            "category_label": CATEGORIES.get(form.category, form.category),
            "version": version,
            "confirm_submit": form.confirm_submit(),
            "itsm_support": form.itsm_support,
            "http_method": form.get_http_method().upper(),
            "fields": fields,
            "initial_values": current,
            "custom_actions": [
                {
                    "id": action.action_id,
                    "label": action.label,
                    "available": True,
                    "reason": "",
                    "style": action.style,
                    "confirmation_required": bool(action.confirmation_text),
                    "dialog": action.dialog is not None,
                }
                for action in actions
            ] + [
                {
                    "id": f"legacy-{index}",
                    "label": button.label,
                    "available": False,
                    "reason": "Tkinter callback необходимо перенести в server action hook",
                    "style": button.style,
                    "confirmation_required": False,
                    "dialog": False,
                }
                for index, button in enumerate(form.get_custom_buttons())
            ],
        }

    def run_action(
        self,
        form_id: str,
        action_id: str,
        environment: str,
        values: Mapping[str, Any],
        version: str,
        confirmation_token: str,
    ) -> dict[str, Any]:
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        action = self._server_action(form, action_id)
        if action.dialog is not None:
            raise ValueError(
                "Это действие открывает диалог; используйте dialog endpoint"
            )
        validation = self.validate(
            form_id,
            environment,
            values,
            version,
            validate_references=action.require_valid_form,
        )
        if action.require_valid_form and not validation.valid:
            return {
                "success": False,
                "validation": asdict(validation),
                "message": "Форма не прошла валидацию",
            }
        fingerprint = self.container.fingerprint(
            f"{form_id}:action:{action_id}",
            environment,
            validation.values,
            form_version(form),
        )
        if action.confirmation_text and not self.container.confirmations.consume(
            confirmation_token, fingerprint
        ):
            return {
                "success": False,
                "confirmation_required": True,
                "confirmation_text": action.confirmation_text,
                "confirmation_token": self.container.confirmations.issue(fingerprint),
            }
        resolver = self.container.new_reference_resolver()
        context = _WebFormContext(
            environment=environment,
            writable_fields=form.fields,
            selected_loader=lambda: self._selected_reference_items(
                form.fields,
                validation.values,
                environment,
                resolver,
            ),
        )
        form.screen = context
        # Contract validation above guarantees a callable direct handler.
        result = action.handler(environment, copy.deepcopy(validation.values))  # type: ignore[misc]
        if result is None:
            result = {}
        if not isinstance(result, Mapping):
            result = {"data": result}
        proposed = result.get("values", {})
        if proposed is not None and not isinstance(proposed, Mapping):
            raise ValueError("Server action values должен быть объектом")
        applied = context.applied_values
        applied.update(copy.deepcopy(dict(proposed or {})))
        # Server actions are allowed to return a partial patch, including data
        # produced by legacy corporate integrations.  Normalise that patch
        # through the same Python field contracts before it reaches React.  In
        # particular, a legacy ``False`` empty marker must never become the
        # visible string "false" when a controlling checkbox reveals a text
        # field.
        structural_errors: list[dict[str, Any]] = []
        combined = copy.deepcopy(validation.values)
        combined.update(copy.deepcopy(applied))
        normalised = self._normalize_object(
            form.fields,
            combined,
            structural_errors,
            environment,
            prefix="",
        )
        normalised = {
            key: value
            for key, value in normalised.items()
            if self._top_level_visible(form.fields, key, normalised)
        }
        applied = {
            key: copy.deepcopy(normalised[key])
            for key in applied
            if key in normalised
        }
        return {
            "success": True,
            "message": str(result.get("message", "Действие выполнено")),
            "values": _json_safe(applied),
            "data": _json_safe(result.get("data")),
        }

    def open_action_dialog(
        self,
        form_id: str,
        action_id: str,
        environment: str,
        form_values: Mapping[str, Any],
        version: str,
    ) -> dict[str, Any]:
        """Create a fresh server-rendered dialog document for one form action."""
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        action = self._server_action(form, action_id)
        dialog = self._require_action_dialog(action)
        form_validation = self.validate(
            form_id,
            environment,
            form_values,
            version,
            validate_references=action.require_valid_form,
        )
        if action.require_valid_form and not form_validation.valid:
            return {
                "success": False,
                "validation_scope": "form",
                "validation": asdict(form_validation),
                "message": "Форма не прошла валидацию",
            }

        resolver = self.container.new_reference_resolver()
        form.screen = _WebFormContext(
            self._selected_reference_items(
                form.fields,
                form_validation.values,
                environment,
                resolver,
            ),
            environment=environment,
        )
        raw_initial = (
            dialog.initial_values(
                environment,
                copy.deepcopy(form_validation.values),
            )
            if callable(dialog.initial_values)
            else dialog.initial_values
        )
        if not isinstance(raw_initial, Mapping):
            raise TypeError("ServerActionDialog.initial_values вернул не mapping")
        initial = self._validate_dialog(
            dialog,
            environment,
            form_validation.values,
            raw_initial,
            form_fields=form.fields,
            validate_references=False,
            run_custom_validator=False,
        )
        contract_errors = [
            item for item in initial.errors
            if item["code"] in {"unknown_field", "invalid_type", "plural_limit"}
        ]
        if contract_errors:
            raise ValueError(
                "Некорректные initial_values диалога: "
                + "; ".join(item["message"] for item in contract_errors)
            )
        return self._dialog_document(
            form,
            action,
            environment,
            form_validation.values,
            initial.values,
        )

    def action_dialog_state(
        self,
        form_id: str,
        action_id: str,
        environment: str,
        form_values: Mapping[str, Any],
        dialog_values: Mapping[str, Any],
        version: str,
    ) -> dict[str, Any]:
        """Recompute conditions and inline options after dialog field changes."""
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        action = self._server_action(form, action_id)
        dialog = self._require_action_dialog(action)
        form_validation = self.validate(
            form_id,
            environment,
            form_values,
            version,
            validate_references=False,
        )
        normalised = self._validate_dialog(
            dialog,
            environment,
            form_validation.values,
            dialog_values,
            form_fields=form.fields,
            validate_references=False,
            run_custom_validator=False,
        )
        return self._dialog_document(
            form,
            action,
            environment,
            form_validation.values,
            normalised.values,
        )

    def action_dialog_options(
        self,
        form_id: str,
        action_id: str,
        field_path: str,
        environment: str,
        form_values: Mapping[str, Any],
        dialog_values: Mapping[str, Any],
        version: str,
        query: str,
        offset: int,
        limit: int,
        refresh: bool,
    ) -> dict[str, Any]:
        """Resolve one dialog reference using only explicitly declared inputs."""
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        action = self._server_action(form, action_id)
        dialog = self._require_action_dialog(action)
        field, siblings = self._find_field_context(dialog.fields, field_path)
        if field.reference is None:
            raise ValueError("Поле диалога не связано со справочником")
        if refresh:
            self.container.reference_cache.invalidate(
                field.reference.resource,
                environment,
            )
        # form_values are intentionally not merged into dialog_values. A
        # handler receives sibling fields with scope="current" and only
        # explicitly named owning-form fields with scope="form". Normalise the
        # browser payload before any value (including uploaded FILE content) is
        # exposed to a private reference handler. This also strips undeclared
        # keys instead of turning the dialog endpoint into a generic parameter
        # tunnel.
        form_validation = self.validate(
            form_id,
            environment,
            form_values,
            version,
            validate_references=False,
        )
        normalised = self._validate_dialog(
            dialog,
            environment,
            form_validation.values,
            dialog_values,
            form_fields=form.fields,
            validate_references=False,
            run_custom_validator=False,
        )
        scoped_values = self._values_for_field_path(
            normalised.values,
            field_path,
        )
        if not _visible(field, scoped_values):
            return {
                "items": [],
                "total": 0,
                "offset": offset,
                "limit": limit,
                "has_more": False,
            }
        all_items = self._resolve_reference(
            field,
            environment,
            scoped_values,
            siblings=siblings,
            dependency_values=form_validation.values,
            dependency_fields=form.fields,
        )
        keys = field.reference.search_keys or (field.reference.label_key,)
        needle = str(query).strip().casefold()
        items = [
            item for item in all_items
            if not needle or any(
                needle in str(item.get(key, "")).casefold() for key in keys
            )
        ]
        selected_values: list[Any] = []
        for key, value in scoped_values.items():
            if key == field.key or (
                key.startswith(f"{field.key}_")
                and key[len(field.key) + 1:].isdigit()
            ):
                selected_values.extend(value if isinstance(value, list) else [value])
        selected_ids = {
            str(value) for value in selected_values if not self._empty(value)
        }
        if selected_ids:
            pinned = [
                item for item in all_items
                if str(item.get(field.reference.value_key, "")) in selected_ids
            ]
            items = pinned + [
                item for item in items
                if str(item.get(field.reference.value_key, "")) not in selected_ids
            ]
        total = len(items)
        page = items[offset:offset + limit]
        return {
            "items": [_public_item(item, field.reference) for item in page],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
        }

    def run_action_dialog_button(
        self,
        form_id: str,
        action_id: str,
        dialog_action_id: str,
        environment: str,
        form_values: Mapping[str, Any],
        dialog_values: Mapping[str, Any],
        version: str,
        confirmation_token: str = "",
    ) -> dict[str, Any]:
        """Execute one dialog button and return authoritative UI patches."""
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        action = self._server_action(form, action_id)
        dialog = self._require_action_dialog(action)
        button = next(
            (item for item in dialog.actions if item.action_id == dialog_action_id),
            None,
        )
        if button is None:
            raise FormNotFoundError(dialog_action_id)

        form_validation = self.validate(
            form_id,
            environment,
            form_values,
            version,
            validate_references=action.require_valid_form,
        )
        if action.require_valid_form and not form_validation.valid:
            return {
                "success": False,
                "validation_scope": "form",
                "validation": asdict(form_validation),
                "message": "Форма не прошла валидацию",
            }
        dialog_validation = self._validate_dialog(
            dialog,
            environment,
            form_validation.values,
            dialog_values,
            form_fields=form.fields,
            validate_references=button.require_valid_dialog,
            run_custom_validator=button.require_valid_dialog,
        )
        if button.require_valid_dialog and not dialog_validation.valid:
            return {
                "success": False,
                "validation_scope": "dialog",
                "validation": asdict(dialog_validation),
                "message": "Поля диалога не прошли валидацию",
            }

        fingerprint = self.container.fingerprint(
            f"{form_id}:action:{action_id}:dialog:{dialog_action_id}",
            environment,
            {
                "form": form_validation.values,
                "dialog": dialog_validation.values,
            },
            form_version(form),
        )
        if button.confirmation_text and not self.container.confirmations.consume(
            confirmation_token,
            fingerprint,
        ):
            return {
                "success": False,
                "confirmation_required": True,
                "confirmation_text": button.confirmation_text,
                "confirmation_token": self.container.confirmations.issue(fingerprint),
            }

        resolver = self.container.new_reference_resolver()
        selected = self._selected_reference_items(
            form.fields,
            form_validation.values,
            environment,
            resolver,
        )
        # Dialog keys intentionally win on collisions: handlers invoked by a
        # dialog naturally expect self.screen.get_field_item("...") to refer
        # to the control the operator just used.
        selected.update(self._selected_reference_items(
            dialog.fields,
            dialog_validation.values,
            environment,
            resolver,
            dependency_values=form_validation.values,
            dependency_fields=form.fields,
        ))
        context = _WebFormContext(
            selected,
            environment=environment,
            writable_fields=form.fields,
        )
        form.screen = context
        raw_result = button.handler(
            environment,
            copy.deepcopy(form_validation.values),
            copy.deepcopy(dialog_validation.values),
        )
        result = self._dialog_action_result(raw_result)

        context.apply_form_data(result.form_values)
        form_patch = context.applied_values
        combined_form = copy.deepcopy(form_validation.values)
        combined_form.update(copy.deepcopy(form_patch))
        patch_errors: list[dict[str, Any]] = []
        normalized_form = self._normalize_object(
            form.fields,
            combined_form,
            patch_errors,
            environment,
            prefix="",
        )
        if any(item["code"] == "invalid_type" for item in patch_errors):
            raise ValueError(
                "Кнопка диалога вернула значение неверного типа: "
                + "; ".join(
                    item["message"] for item in patch_errors
                    if item["code"] == "invalid_type"
                )
            )
        normalized_form = {
            key: value
            for key, value in normalized_form.items()
            if self._top_level_visible(form.fields, key, normalized_form)
        }
        form_patch = {
            key: copy.deepcopy(normalized_form[key])
            for key in form_patch
            if key in normalized_form
        }

        combined_dialog = copy.deepcopy(dialog_validation.values)
        combined_dialog.update(copy.deepcopy(dict(result.dialog_values)))
        next_dialog = self._validate_dialog(
            dialog,
            environment,
            normalized_form,
            combined_dialog,
            form_fields=form.fields,
            validate_references=False,
            run_custom_validator=False,
        )
        close_dialog = (
            button.close_on_success
            if result.close_dialog is None
            else bool(result.close_dialog)
        )
        response = self._dialog_document(
            form,
            action,
            environment,
            normalized_form,
            next_dialog.values,
        )
        response.update({
            "success": True,
            "message": str(result.message or "Действие выполнено"),
            "form_values": _json_safe(form_patch),
            "data": _json_safe(result.data),
            "close_dialog": close_dialog,
        })
        return response

    @staticmethod
    def _require_action_dialog(action: ServerAction) -> ServerActionDialog:
        if action.dialog is None:
            raise ValueError("ServerAction не содержит кастомный диалог")
        return action.dialog

    def _dialog_document(
        self,
        form: BaseForm,
        action: ServerAction,
        environment: str,
        form_values: Mapping[str, Any],
        dialog_values: Mapping[str, Any],
    ) -> dict[str, Any]:
        dialog = self._require_action_dialog(action)
        reference_base = (
            f"/api/v1/forms/{form.form_id}/actions/{action.action_id}/dialog"
        )
        return {
            "success": True,
            "id": action.action_id,
            "title": dialog.title,
            "description": dialog.description,
            "form_version": form_version(form),
            "values": _json_safe(dict(dialog_values)),
            "fields": [
                self._field_document(
                    form,
                    field,
                    environment,
                    dialog_values,
                    siblings=dialog.fields,
                    reference_base=reference_base,
                    dependency_values=form_values,
                    dependency_fields=form.fields,
                )
                for field in dialog.fields
            ],
            "actions": [
                {
                    "id": item.action_id,
                    "label": item.label,
                    "style": str(item.style).strip().casefold(),
                    "confirmation_required": bool(item.confirmation_text),
                    "requires_valid_dialog": item.require_valid_dialog,
                    "close_on_success": item.close_on_success,
                }
                for item in dialog.actions
            ],
        }

    def _validate_dialog(
        self,
        dialog: ServerActionDialog,
        environment: str,
        form_values: Mapping[str, Any],
        dialog_values: Mapping[str, Any],
        *,
        form_fields: Iterable[FieldDefinition] = (),
        validate_references: bool,
        run_custom_validator: bool,
    ) -> RuntimeValidation:
        errors: list[dict[str, Any]] = []
        canonical = self._normalize_object(
            dialog.fields,
            self._with_defaults(dialog.fields, dict(dialog_values)),
            errors,
            environment,
            prefix="",
        )
        visible = tuple(
            field.key for field in dialog.fields if _visible(field, canonical)
        )
        canonical = {
            key: value
            for key, value in canonical.items()
            if self._top_level_visible(dialog.fields, key, canonical)
        }
        if validate_references:
            self._validate_references(
                dialog.fields,
                canonical,
                environment,
                errors,
                dependency_values=form_values,
                dependency_fields=form_fields,
            )
        if run_custom_validator and dialog.validate is not None:
            raw_issues = dialog.validate(
                environment,
                copy.deepcopy(dict(form_values)),
                copy.deepcopy(canonical),
            )
            if isinstance(raw_issues, (str, FormValidationIssue, Mapping)):
                issues: Iterable[Any] = (raw_issues,)
            else:
                issues = tuple(raw_issues or ())
            existing = {item["message"] for item in errors}
            for issue in issues:
                field, code, message = self._domain_validation_issue(
                    issue,
                    dialog.fields,
                    canonical,
                )
                if message and message not in existing:
                    errors.append({"field": field, "code": code, "message": message})
                    existing.add(message)
        return RuntimeValidation(not errors, canonical, tuple(errors), visible)

    @staticmethod
    def _dialog_action_result(value: Any) -> ServerDialogActionResult:
        if value is None:
            return ServerDialogActionResult()
        if isinstance(value, ServerDialogActionResult):
            return value
        if not isinstance(value, Mapping):
            return ServerDialogActionResult(data=value)
        known = {
            "message",
            "form_values",
            "values",
            "dialog_values",
            "data",
            "close_dialog",
        }
        unexpected = set(value) - known
        if unexpected:
            raise ValueError(
                "Кнопка диалога вернула неизвестные поля: "
                + ", ".join(sorted(str(item) for item in unexpected))
            )
        if "form_values" in value and "values" in value:
            raise ValueError("Используйте form_values или values, но не оба сразу")
        form_values = value.get("form_values", value.get("values", {})) or {}
        dialog_values = value.get("dialog_values") or {}
        if not isinstance(form_values, Mapping):
            raise TypeError("form_values результата диалога должен быть mapping")
        if not isinstance(dialog_values, Mapping):
            raise TypeError("dialog_values результата диалога должен быть mapping")
        raw_close = value.get("close_dialog")
        if raw_close is not None and not isinstance(raw_close, bool):
            raise TypeError("close_dialog результата диалога должен быть bool или None")
        return ServerDialogActionResult(
            message=str(value.get("message") or "Действие выполнено"),
            form_values=form_values,
            dialog_values=dialog_values,
            data=value.get("data"),
            close_dialog=raw_close,
        )

    def _field_document(
        self,
        form: BaseForm,
        field: FieldDefinition,
        environment: str,
        values: Mapping[str, Any],
        *,
        prefix: str = "",
        siblings: Optional[Iterable[FieldDefinition]] = None,
        reference_namespace: str = "forms",
        reference_base: str = "",
        dependency_values: Optional[Mapping[str, Any]] = None,
        dependency_fields: Optional[Iterable[FieldDefinition]] = None,
    ) -> dict[str, Any]:
        path = f"{prefix}.{field.key}" if prefix else field.key
        visible = _visible(field, values)
        document: dict[str, Any] = {
            "key": field.key,
            "path": path,
            "label": field.label,
            "type": field.field_type.value,
            "required": field.required,
            "visible": visible,
            "dynamic": field.condition is not None,
            "placeholder": field.placeholder,
            "default": _json_safe(_declared_default(field)),
            "hint": field.hint,
            "file_type": field.file_type,
            "width": field.width,
            "plural": field.plural,
            "plural_max": field.plural_max,
            "depends_on": field.depends_on or None,
            "depends_on_field": field.depends_on_field or None,
            "reference_dependencies": [
                {
                    "field": item.field,
                    "parameter": item.parameter or item.field,
                    "item_field": item.item_field or None,
                    "scope": str(item.scope or "current").strip().casefold(),
                }
                for item in field.reference_dependencies
            ],
        }
        if field.plural:
            document["plural_contract"] = {
                "first_instance_path": path,
                "additional_instance_path_template": f"{path}_{{instance_number}}",
                "additional_instance_number_starts_at": 2,
                "draft_array_supported": field.field_type == FieldType.BLOCK,
            }
        if field.reference:
            ref = field.reference
            document["reference"] = {
                "source": ref.source,
                "resource": ref.resource,
                "value_key": ref.value_key,
                "label_key": ref.label_key,
                "search_keys": list(ref.search_keys or (ref.label_key,)),
                "detail_keys": list(ref.detail_keys),
                "required_params": list(ref.required_params),
                "endpoint": (
                    (
                        reference_base.rstrip("/")
                        if reference_base
                        else f"/api/v1/{reference_namespace}/{form.form_id}"
                    )
                    + f"/fields/{path}/options"
                ),
            }
            if ref.source == "local" and visible:
                items = self._resolve_reference(
                    field,
                    environment,
                    values,
                    siblings=siblings,
                    dependency_values=dependency_values,
                    dependency_fields=dependency_fields,
                )
                public_items = [_public_item(item, ref) for item in items]
                rendered_size = len(json.dumps(
                    public_items,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8"))
                if (
                    len(public_items) <= _INLINE_REFERENCE_MAX_ITEMS
                    and rendered_size <= _INLINE_REFERENCE_MAX_BYTES
                ):
                    document["options"] = public_items
        if field.field_type == FieldType.BLOCK:
            def nested_documents(instance_key: str) -> list[dict[str, Any]]:
                block_values = values.get(instance_key)
                nested_values = (
                    block_values if isinstance(block_values, Mapping) else {}
                )
                instance_path = (
                    f"{prefix}.{instance_key}" if prefix else instance_key
                )
                return [
                    self._field_document(
                        form,
                        nested,
                        environment,
                        nested_values,
                        prefix=instance_path,
                        siblings=field.block_fields,
                        reference_namespace=reference_namespace,
                        reference_base=reference_base,
                        dependency_values=dependency_values,
                        dependency_fields=dependency_fields,
                    )
                    for nested in field.block_fields
                ]

            document["fields"] = nested_documents(field.key)
            if field.plural:
                additional = sorted(
                    (
                        (int(match.group(2)), key)
                        for key in values
                        if (
                            (match := _PLURAL_RE.match(key)) is not None
                            and match.group(1) == field.key
                        )
                    ),
                    key=lambda item: item[0],
                )
                if additional:
                    document["instances"] = {
                        key: nested_documents(key) for _index, key in additional
                    }
        return document

    def state(
        self, form_id: str, environment: str, values: Mapping[str, Any], version: str = ""
    ) -> dict[str, Any]:
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        return self.describe(form_id, environment, values)

    def validate(
        self,
        form_id: str,
        environment: str,
        values: Mapping[str, Any],
        version: str = "",
        *,
        validate_references: bool = True,
    ) -> RuntimeValidation:
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        raw = self._with_defaults(form.fields, dict(values))
        errors: list[dict[str, Any]] = []
        canonical = self._normalize_object(
            form.fields, raw, errors, environment, prefix=""
        )
        visible_fields = tuple(
            field.key for field in form.fields if _visible(field, canonical)
        )
        canonical = {
            key: value
            for key, value in canonical.items()
            if self._top_level_visible(form.fields, key, canonical)
        }
        if validate_references:
            self._validate_references(form.fields, canonical, environment, errors)

        try:
            domain_errors = form.validate(canonical)
        except Exception as exc:
            _log.exception("domain validation crashed form=%s", form_id)
            errors.append({
                "field": None,
                "code": "domain_validation_failed",
                "message": f"Ошибка Python-валидатора формы: {exc}",
            })
        else:
            existing_messages = {item["message"] for item in errors}
            if isinstance(domain_errors, (str, FormValidationIssue, Mapping)):
                domain_errors = [domain_errors]
            for issue in domain_errors or []:
                field, code, clean = self._domain_validation_issue(
                    issue,
                    form.fields,
                    canonical,
                )
                if not clean:
                    continue
                required_match = re.fullmatch(
                    r'Поле "(?P<label>.+)" обязательно для заполнения', clean
                )
                if required_match and any(
                    item["code"] == "required"
                    and item["message"]
                    == f'Поле "{required_match.group("label")}" обязательно'
                    for item in errors
                ):
                    # BaseForm.validate repeats the structural required-field
                    # check. Keep the field-addressable runtime error only.
                    continue
                if clean not in existing_messages:
                    errors.append({
                        "field": field,
                        "code": code,
                        "message": clean,
                    })
                    existing_messages.add(clean)
        return RuntimeValidation(not errors, canonical, tuple(errors), visible_fields)

    def preview(
        self, form_id: str, environment: str, values: Mapping[str, Any], version: str
    ) -> dict[str, Any]:
        validation = self.validate(form_id, environment, values, version)
        if not validation.valid:
            return {
                "valid": False,
                "values": validation.values,
                "errors": list(validation.errors),
                "visible_fields": list(validation.visible_fields),
            }
        form = self.get_form(form_id, environment)
        payload = form.build_payload(validation.values)
        endpoint = form.get_submit_endpoint(environment)
        if not endpoint:
            return {
                "valid": False,
                "values": validation.values,
                "errors": [{
                    "field": None,
                    "code": "endpoint_missing",
                    "message": f"URL не задан для окружения {environment!r}",
                }],
                "visible_fields": list(validation.visible_fields),
            }
        fingerprint = self.container.fingerprint(
            form_id, environment, validation.values, form_version(form)
        )
        confirmation_token = (
            self.container.confirmations.issue(fingerprint)
            if form.confirm_submit()
            else ""
        )
        return {
            "valid": True,
            "values": validation.values,
            "errors": [],
            "visible_fields": list(validation.visible_fields),
            "method": form.get_http_method().upper(),
            "endpoint": endpoint,
            "payload": _json_safe(payload),
            "confirmation_required": form.confirm_submit(),
            "confirmation_text": form.build_confirm_text(
                environment, endpoint, form.get_http_method().upper(), payload
            ) if form.confirm_submit() else "",
            "confirmation_token": confirmation_token,
        }

    def submit(
        self,
        form_id: str,
        environment: str,
        values: Mapping[str, Any],
        version: str,
        confirmation_token: str,
    ) -> dict[str, Any]:
        validation = self.validate(form_id, environment, values, version)
        if not validation.valid:
            return {
                "success": False,
                "validation": asdict(validation),
                "message": "Форма не прошла валидацию",
            }
        form = self.get_form(form_id, environment)
        current_version = form_version(form)
        if form.confirm_submit():
            fingerprint = self.container.fingerprint(
                form_id, environment, validation.values, current_version
            )
            if not self.container.confirmations.consume(confirmation_token, fingerprint):
                return {
                    "success": False,
                    "code": "confirmation_required",
                    "message": "Подтверждение отсутствует, истекло или относится к другим данным",
                }

        resolver = self.container.new_reference_resolver()
        form.screen = _WebFormContext(
            self._selected_reference_items(
                form.fields, validation.values, environment, resolver
            )
        )
        submit_service = self.container.new_submit_service()
        result = submit_service.submit(form, validation.values, environment)
        if not result.success:
            return {
                "success": False,
                "code": "submit_failed",
                "message": result.message,
                "response": _json_safe(result.raw_response),
            }
        snapshot = {field.key: field.field_type.value for field in form.fields}
        self.container.run_storage.save(
            form_id, environment, validation.values, snapshot
        )
        result_config = form.get_result_config()
        polling = bool(result_config.poll_interval_ms)
        submission = self.container.submissions.create(
            form_id, environment, result.raw_response, result.payload, polling
        )
        status = form.get_result_status(environment, result.raw_response)
        return {
            "success": True,
            "message": result.message,
            "submission_id": submission.submission_id,
            "status": status.value,
            "title": result_config.title or form.title,
            "content": form.build_result_content(environment, result.raw_response),
            "response": _json_safe(result.raw_response),
            "payload": _json_safe(result.payload),
            "polling": polling,
            "poll_interval_ms": result_config.poll_interval_ms,
        }

    def poll(self, submission_id: str) -> dict[str, Any]:
        state = self.container.submissions.get(submission_id)
        if state is None:
            raise FormNotFoundError("submission")
        form = self.get_form(state.form_id, state.environment)
        if not state.polling:
            return {"polling": False, "status": "stopped"}
        endpoint = form.get_poll_endpoint(state.environment, state.response)
        if not endpoint:
            state.polling = False
            self.container.submissions.update(state)
            return {"polling": False, "status": "stopped", "content": ""}
        client = self.container.new_http_client()
        submit_service = self.container.submit_service_for(client)
        submit_service.set_auth(form, state.environment)
        response = client.get(endpoint)
        status = form.get_poll_status(state.environment, response)
        keep_polling = form.should_continue_polling(state.environment, response)
        state.polling = bool(keep_polling)
        self.container.submissions.update(state)
        return {
            "polling": state.polling,
            "status": status.value,
            "content": form.build_poll_content(state.environment, response),
            "response": _json_safe(response),
            "info": (
                form.build_info_after_polling(state.environment, state.payload)
                if not keep_polling and form.show_info_after_polling
                else ""
            ),
        }

    def fetch_ticket(
        self,
        form_id: str,
        environment: str,
        ticket_id: str,
        current_values: Optional[Mapping[str, Any]] = None,
        version: str = "",
    ) -> dict[str, Any]:
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        self._check_version(form, version)
        if not form.itsm_support:
            raise ValueError("Эта форма не поддерживает прямое заполнение из ITSM")
        context = _WebFormContext(
            environment=environment,
            writable_fields=form.fields,
        )
        form.screen = context
        raw_result = form.fetch_from_itsm(environment, ticket_id)
        if isinstance(raw_result, ITSMFetchResult):
            result = raw_result
        elif raw_result is None or isinstance(raw_result, Mapping):
            # Public compatibility contract: every pre-refactor mapping is an
            # exact deterministic field patch.
            result = ITSMFetchResult.deterministic(raw_result or {})
        else:
            raise ValueError(
                "fetch_from_itsm должен вернуть ITSMFetchResult "
                "или legacy mapping field_key -> value"
            )
        _log.info(
            "ITSM form hook completed form=%s environment=%s mode=%s",
            form_id,
            environment,
            result.mode.value,
        )

        if result.mode is ITSMFetchMode.AI:
            if context.applied_values:
                raise ValueError(
                    "В режиме ai не вызывайте apply_form_data: "
                    "верните исходные данные в ITSMFetchResult.ai(context)"
                )
            if self.container.ai is None:
                raise FormAIUnavailableError(
                    "AI-сервис формы не инициализирован"
                )
            safe_context = sanitize(dict(result.context or {}))
            if not isinstance(safe_context, Mapping):
                raise ValueError("ITSM AI context должен быть JSON-объектом")
            try:
                corporate_prompt = resolve_itsm_ai_prompt(
                    form.itsm_service,
                    ticket_id=ticket_id,
                    environment=environment,
                    ticket_context=safe_context,
                    form_id=form_id,
                    prompt_override=self.container.itsm_prompt_settings.prompt_for,
                )
            except Exception as exc:
                _log.warning(
                    "corporate ITSM AI prompt failed form=%s environment=%s "
                    "error_type=%s",
                    form_id,
                    environment,
                    type(exc).__name__,
                    exc_info=True,
                )
                raise ValueError(
                    "Не удалось выбрать корпоративные AI-инструкции для "
                    f"заявки: {type(exc).__name__}"
                ) from exc
            instructions = "\n\n".join(
                item
                for item in (
                    corporate_prompt.instructions if corporate_prompt else "",
                    redact_text(result.instruction),
                )
                if item
            )
            if len(instructions) > MAX_ITSM_AI_INSTRUCTIONS_CHARS:
                raise ValueError(
                    "Суммарные ITSM AI-инструкции превышают "
                    f"{MAX_ITSM_AI_INSTRUCTIONS_CHARS} символов"
                )
            try:
                return self.container.ai.start_form_ticket_fill(
                    form_id=form_id,
                    environment=environment,
                    form_version=form_version(form),
                    ticket_id=ticket_id,
                    source_context=safe_context,
                    ticket_type=(
                        corporate_prompt.ticket_type if corporate_prompt else ""
                    ),
                    instruction=instructions,
                    current_values=current_values or {},
                )
            except RuntimeError as exc:
                raise FormAIUnavailableError(str(exc)) from exc

        # Reuse the headless FormScreen compatibility filter so a legacy hook's
        # extra metadata never becomes an unknown form field.
        context.apply_form_data(result.values)
        patch = context.applied_values
        values = copy.deepcopy(dict(current_values or {}))
        values.update(patch)
        validation = self.validate(
            form_id,
            environment,
            values,
            form_version(form),
            validate_references=False,
        )
        return {
            "mode": ITSMFetchMode.DETERMINISTIC.value,
            "values": validation.values,
            "errors": list(validation.errors),
            "valid": validation.valid,
        }

    def options(
        self,
        form_id: str,
        field_path: str,
        environment: str,
        values: Mapping[str, Any],
        query: str,
        offset: int,
        limit: int,
        refresh: bool,
    ) -> dict[str, Any]:
        self._ensure_environment(environment)
        form = self.get_form(form_id, environment)
        field, siblings = self._find_field_context(form.fields, field_path)
        if field.reference is None:
            raise ValueError("Поле не связано со справочником")
        if refresh:
            self.container.reference_cache.invalidate(
                field.reference.resource, environment
            )
        scoped_values = self._values_for_field_path(values, field_path)
        all_items = self._resolve_reference(
            field, environment, scoped_values, siblings=siblings
        )
        items = all_items
        keys = field.reference.search_keys or (field.reference.label_key,)
        needle = query.strip().casefold()
        if needle:
            items = [
                item for item in items
                if any(needle in str(item.get(key, "")).casefold() for key in keys)
            ]
        # Keep already selected IDs representable even when pagination or the
        # current search query would otherwise omit them.
        selected_values: list[Any] = []
        for key, value in scoped_values.items():
            if key == field.key or (
                key.startswith(f"{field.key}_") and key[len(field.key) + 1:].isdigit()
            ):
                selected_values.extend(value if isinstance(value, list) else [value])
        selected_ids = {str(value) for value in selected_values if not self._empty(value)}
        if selected_ids:
            selected_items = [
                item for item in all_items
                if str(item.get(field.reference.value_key, "")) in selected_ids
            ]
            items = selected_items + [
                item for item in items
                if str(item.get(field.reference.value_key, "")) not in selected_ids
            ]
        total = len(items)
        selected = items[offset:offset + limit]
        return {
            "items": [_public_item(item, field.reference) for item in selected],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(selected) < total,
        }

    def search(
        self,
        kind: str,
        environments: Iterable[str],
        query: str,
        limit: int,
        refresh: bool,
    ) -> dict[str, Any]:
        reference = self.container.search_catalogs.get(kind)
        if reference is None:
            raise ValueError("Неизвестный тип поиска")
        needle = query.strip().casefold()
        result: list[dict[str, Any]] = []
        resolver = self.container.new_reference_resolver()
        for environment in dict.fromkeys(environments):
            self._ensure_environment(environment)
            if refresh:
                self.container.reference_cache.invalidate(reference.resource, environment)
            for item in resolver.resolve(reference, environment):
                if not any(
                    needle in str(item.get(key, "")).casefold()
                    for key in reference.search_keys
                ):
                    continue
                result.append({
                    "environment": environment,
                    "label": _json_safe(item.get(reference.label_key, "")),
                    "value": _json_safe(item.get(reference.value_key, "")),
                    "item": _public_item(item, reference),
                })
                if len(result) >= limit:
                    return {"items": result, "truncated": True}
        return {"items": result, "truncated": False}

    def search_cache_status(
        self,
        kind: str,
        environments: Iterable[str],
    ) -> dict[str, Any]:
        """Describe when each selected search catalog was last cached."""
        reference = self.container.search_catalogs.get(kind)
        if reference is None:
            raise ValueError("Неизвестный тип поиска")
        items = []
        for environment in dict.fromkeys(environments):
            self._ensure_environment(environment)
            items.append({
                "environment": environment,
                "updated_at": self.container.reference_cache.get_timestamp(
                    reference.resource, environment
                ),
            })
        return {"items": items}

    def refresh_search_catalog(
        self,
        kind: str,
        environments: Iterable[str],
    ) -> dict[str, Any]:
        """Invalidate and eagerly reload a search catalog for selected ENV values."""
        reference = self.container.search_catalogs.get(kind)
        if reference is None:
            raise ValueError("Неизвестный тип поиска")
        resolver = self.container.new_reference_resolver()
        items = []
        for environment in dict.fromkeys(environments):
            self._ensure_environment(environment)
            self.container.reference_cache.invalidate(
                reference.resource, environment
            )
            loaded = resolver.resolve(reference, environment)
            items.append({
                "environment": environment,
                "updated_at": self.container.reference_cache.get_timestamp(
                    reference.resource, environment
                ),
                "count": len(loaded),
            })
        return {"items": items}

    def _normalize_object(
        self,
        fields: Iterable[FieldDefinition],
        raw: Mapping[str, Any],
        errors: list[dict[str, Any]],
        environment: str,
        *,
        prefix: str,
    ) -> dict[str, Any]:
        definitions = {field.key: field for field in fields}
        result: dict[str, Any] = {}
        for key in raw:
            base = key
            match = _PLURAL_RE.match(key)
            if match and match.group(1) in definitions and definitions[match.group(1)].plural:
                base = match.group(1)
                maximum = definitions[base].plural_max
                if maximum is not None and int(match.group(2)) > maximum:
                    errors.append(self._error(key, "plural_limit", "Превышено число значений"))
                    continue
            if base not in definitions:
                errors.append(self._error(key, "unknown_field", "Неизвестное поле формы"))

        current = self._with_defaults(tuple(fields), dict(raw))
        for key, value in current.items():
            base = key
            match = _PLURAL_RE.match(key)
            if match and match.group(1) in definitions and definitions[match.group(1)].plural:
                base = match.group(1)
            field = definitions.get(base)
            if field is None:
                continue
            path = f"{prefix}.{key}" if prefix else key
            try:
                result[key] = self._coerce(field, value, errors, environment, path)
            except (TypeError, ValueError) as exc:
                errors.append(self._error(path, "invalid_type", str(exc)))
        for field in fields:
            if not _visible(field, result):
                result.pop(field.key, None)
                continue
            value = result.get(field.key)
            if field.required and self._empty(value):
                path = f"{prefix}.{field.key}" if prefix else field.key
                errors.append(self._error(path, "required", f'Поле "{field.label}" обязательно'))
        return result

    def _coerce(
        self,
        field: FieldDefinition,
        value: Any,
        errors: list[dict[str, Any]],
        environment: str,
        path: str,
    ) -> Any:
        if value is None:
            return None
        if field.field_type in _STRING_FIELD_TYPES:
            if isinstance(value, (bool, dict, list, tuple, set)):
                raise TypeError("Ожидалось строковое значение")
            text = str(value)
            max_length = 1_000_000 if field.field_type == FieldType.FILE else 100_000
            if len(text) > max_length:
                raise ValueError(f"Значение длиннее {max_length} символов")
            return text
        if field.field_type == FieldType.MULTISELECT:
            if not isinstance(value, (list, tuple)):
                raise TypeError("Ожидался список значений")
            if len(value) > 1000:
                raise ValueError("Выбрано больше 1000 значений")
            if any(isinstance(item, bool) for item in value):
                raise TypeError("Элементы списка должны быть строковыми идентификаторами")
            return [str(item) for item in value]
        if field.field_type == FieldType.CHECKBOX:
            if isinstance(value, bool):
                return value
            if str(value).strip().casefold() in {"1", "true", "yes", "on", "да"}:
                return True
            if str(value).strip().casefold() in {"0", "false", "no", "off", "нет", ""}:
                return False
            raise TypeError("Ожидалось логическое значение")
        if field.field_type == FieldType.NUMBER:
            if isinstance(value, bool):
                raise TypeError("Ожидалось число")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("Число должно быть конечным")
            return int(number) if number.is_integer() else number
        if field.field_type == FieldType.BLOCK:
            if not isinstance(value, Mapping):
                raise TypeError("Ожидался объект блока")
            return self._normalize_object(
                field.block_fields,
                value,
                errors,
                environment,
                prefix=path,
            )
        return _json_safe(value)

    def _validate_references(
        self,
        fields: Iterable[FieldDefinition],
        values: Mapping[str, Any],
        environment: str,
        errors: list[dict[str, Any]],
        *,
        prefix: str = "",
        dependency_values: Optional[Mapping[str, Any]] = None,
        dependency_fields: Iterable[FieldDefinition] = (),
    ) -> None:
        field_definitions = tuple(fields)
        definitions = {field.key: field for field in field_definitions}
        for key, value in values.items():
            base = key
            match = _PLURAL_RE.match(key)
            if match and match.group(1) in definitions:
                base = match.group(1)
            field = definitions.get(base)
            if field is None or not _visible(field, values):
                continue
            path = f"{prefix}.{key}" if prefix else key
            if field.field_type == FieldType.BLOCK and isinstance(value, Mapping):
                self._validate_references(
                    field.block_fields,
                    value,
                    environment,
                    errors,
                    prefix=path,
                    dependency_values=dependency_values,
                    dependency_fields=dependency_fields,
                )
                continue
            if field.reference is None or self._empty(value):
                continue
            items = self._resolve_reference(
                field,
                environment,
                values,
                siblings=field_definitions,
                dependency_values=dependency_values,
                dependency_fields=dependency_fields,
            )
            if not items:
                errors.append(self._error(
                    path,
                    "reference_unavailable",
                    f'Справочник "{field.label}" недоступен или пуст',
                ))
                continue
            allowed = {str(item.get(field.reference.value_key, "")) for item in items}
            selected = value if isinstance(value, list) else [value]
            unknown = [str(item) for item in selected if str(item) not in allowed]
            if unknown:
                errors.append(self._error(
                    path,
                    "invalid_reference",
                    f'Значение отсутствует в справочнике "{field.label}"',
                ))

    def _selected_reference_items(
        self,
        fields: Iterable[FieldDefinition],
        values: Mapping[str, Any],
        environment: str,
        resolver: Any,
        *,
        dependency_values: Optional[Mapping[str, Any]] = None,
        dependency_fields: Iterable[FieldDefinition] = (),
    ) -> dict[str, list[dict[str, Any]]]:
        selected: dict[str, list[dict[str, Any]]] = {}
        field_definitions = tuple(fields)
        for field in field_definitions:
            value = values.get(field.key)
            if field.field_type == FieldType.BLOCK and isinstance(value, Mapping):
                selected.update(self._selected_reference_items(
                    field.block_fields,
                    value,
                    environment,
                    resolver,
                    dependency_values=dependency_values,
                    dependency_fields=dependency_fields,
                ))
                continue
            if field.reference is None:
                continue
            instance_keys = [field.key]
            if field.plural:
                instance_keys.extend(
                    key for key in values
                    if key.startswith(f"{field.key}_")
                    and key[len(field.key) + 1:].isdigit()
                )
            populated = [
                key for key in instance_keys if not self._empty(values.get(key))
            ]
            if not populated:
                continue
            items = self._resolve_reference(
                field,
                environment,
                values,
                siblings=field_definitions,
                resolver=resolver,
                dependency_values=dependency_values,
                dependency_fields=dependency_fields,
            )
            for instance_key in populated:
                instance_value = values.get(instance_key)
                wanted = {
                    str(item)
                    for item in (
                        instance_value
                        if isinstance(instance_value, list)
                        else [instance_value]
                    )
                }
                selected[instance_key] = [
                    dict(item)
                    for item in items
                    if str(item.get(field.reference.value_key, "")) in wanted
                ]
        return selected

    def _resolve_reference(
        self,
        field: FieldDefinition,
        environment: str,
        values: Mapping[str, Any],
        *,
        siblings: Optional[Iterable[FieldDefinition]] = None,
        resolver: Any = None,
        dependency_values: Optional[Mapping[str, Any]] = None,
        dependency_fields: Optional[Iterable[FieldDefinition]] = None,
    ) -> list[dict[str, Any]]:
        if field.reference is None:
            return []
        active_resolver = resolver or self.container.new_reference_resolver()
        params = self._reference_params(
            field,
            values,
            tuple(siblings or ()),
            environment,
            active_resolver,
            dependency_values=dependency_values,
            dependency_fields=tuple(dependency_fields or ()),
        )
        if field.reference.required_params and (
            not params
            or any(self._empty(params.get(key)) for key in field.reference.required_params)
        ):
            return []
        return active_resolver.resolve(
            field.reference,
            environment,
            params,
        )

    def _reference_params(
        self,
        field: FieldDefinition,
        values: Mapping[str, Any],
        siblings: Iterable[FieldDefinition],
        environment: str,
        resolver: Any,
        *,
        dependency_values: Optional[Mapping[str, Any]] = None,
        dependency_fields: Iterable[FieldDefinition] = (),
    ) -> Optional[dict[str, Any]]:
        dependencies = list(field.reference_dependencies)
        if field.depends_on:
            legacy = ReferenceDependency(
                field=field.depends_on,
                parameter=field.depends_on,
                item_field=field.depends_on_field,
            )
            if not any(
                item.field == legacy.field
                and (item.parameter or item.field) == legacy.parameter
                for item in dependencies
            ):
                dependencies.insert(0, legacy)
        if not dependencies:
            return None

        params: dict[str, Any] = {}
        sibling_definitions = tuple(siblings)
        owning_definitions = tuple(dependency_fields)
        for dependency in dependencies:
            dependency_scope = str(dependency.scope or "current").strip().casefold()
            source_values = (
                dependency_values
                if dependency_scope == "form" and dependency_values is not None
                else values
            )
            source_definitions = (
                owning_definitions
                if dependency_scope == "form"
                else sibling_definitions
            )
            parent_value = source_values.get(dependency.field)
            if dependency.item_field:
                if isinstance(parent_value, Mapping):
                    parent_value = parent_value.get(dependency.item_field)
                elif not self._empty(parent_value):
                    parent = next(
                        (
                            item for item in source_definitions
                            if item.key == dependency.field
                        ),
                        None,
                    )
                    if parent is None or parent.reference is None:
                        parent_value = None
                    else:
                        parent_items = self._resolve_reference(
                            parent,
                            environment,
                            source_values,
                            siblings=source_definitions,
                            resolver=resolver,
                            dependency_values=dependency_values,
                            dependency_fields=owning_definitions,
                        )
                        selected = next((
                            item for item in parent_items
                            if str(item.get(parent.reference.value_key, ""))
                            == str(parent_value)
                        ), None)
                        parent_value = (
                            selected.get(dependency.item_field)
                            if selected is not None
                            else None
                        )
            if not self._empty(parent_value):
                params[dependency.parameter or dependency.field] = parent_value
        return params or None

    @staticmethod
    def _values_for_field_path(
        values: Mapping[str, Any], field_path: str
    ) -> Mapping[str, Any]:
        """Return the object containing a nested field, preserving root behavior."""
        parts = [part for part in field_path.split(".") if part]
        current: Mapping[str, Any] = values
        for part in parts[:-1]:
            candidate = current.get(part)
            if not isinstance(candidate, Mapping):
                return {}
            current = candidate
        return current

    @classmethod
    def _with_defaults(
        cls,
        fields: Iterable[FieldDefinition],
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply defaults to the complete form tree, including block instances.

        A block is represented by a nested mapping.  Applying defaults only to
        the root made a nested unchecked ``CHECKBOX`` indistinguishable from an
        absent value during the initial schema projection.  Conditions using
        an explicit comparison such as ``values["enabled"] is False`` therefore
        changed behavior only after the checkbox had been toggled.  A checkbox
        without an explicit default is materialised as ``False`` to match both
        the React and legacy Tkinter controls.

        Preserve the legacy flat/plural representation while materialising a
        block only when it has its own default or at least one nested default.
        Existing block mappings are copied before recursion so caller-owned
        values are never mutated.
        """
        result = dict(values)
        for field in tuple(fields):
            if field.key not in result:
                declared_default = _declared_default(field)
                if declared_default is not None:
                    result[field.key] = copy.deepcopy(declared_default)
                elif field.field_type == FieldType.CHECKBOX:
                    result[field.key] = False
            if field.field_type != FieldType.BLOCK:
                continue

            instance_keys = [
                key
                for key in result
                if key == field.key
                or (
                    field.plural
                    and (match := _PLURAL_RE.match(key)) is not None
                    and match.group(1) == field.key
                )
            ]
            if field.key not in result:
                nested_defaults = cls._with_defaults(field.block_fields, {})
                if nested_defaults:
                    result[field.key] = nested_defaults
                    instance_keys.insert(0, field.key)

            for key in instance_keys:
                block_values = result.get(key)
                if isinstance(block_values, Mapping):
                    result[key] = cls._with_defaults(
                        field.block_fields,
                        dict(block_values),
                    )
        return result

    @staticmethod
    def _empty(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    @staticmethod
    def _error(field: Optional[str], code: str, message: str) -> dict[str, Any]:
        return {"field": field, "code": code, "message": message}

    @classmethod
    def _domain_validation_issue(
        cls,
        issue: Any,
        fields: Iterable[FieldDefinition],
        values: Mapping[str, Any],
    ) -> tuple[Optional[str], str, str]:
        """Normalise legacy and field-aware results returned by ``validate``."""
        explicit_field: Optional[str] = None
        code = "domain_validation"
        if isinstance(issue, FormValidationIssue):
            explicit_field = issue.field
            code = issue.code or code
            message = issue.message
        elif isinstance(issue, Mapping):
            raw_field = issue.get("field")
            explicit_field = (
                str(raw_field) if raw_field is not None and raw_field != "" else None
            )
            code = str(issue.get("code") or code)
            message = issue.get("message", "")
        else:
            message = issue
        clean = str(message).strip()
        candidates = cls._validation_field_candidates(fields, values)
        field = cls._match_validation_field(explicit_field, clean, candidates)
        return field, code, clean

    @classmethod
    def _validation_field_candidates(
        cls,
        fields: Iterable[FieldDefinition],
        values: Mapping[str, Any],
        *,
        prefix: str = "",
    ) -> list[tuple[str, str, str]]:
        candidates: list[tuple[str, str, str]] = []
        for field in fields:
            instance_keys = [field.key]
            if field.plural:
                instance_keys.extend(
                    key for key in values
                    if key.startswith(f"{field.key}_")
                    and key[len(field.key) + 1:].isdigit()
                )
            for key in dict.fromkeys(instance_keys):
                path = f"{prefix}.{key}" if prefix else key
                candidates.append((path, key, field.label))
                value = values.get(key)
                if field.field_type == FieldType.BLOCK and isinstance(value, Mapping):
                    candidates.extend(cls._validation_field_candidates(
                        field.block_fields,
                        value,
                        prefix=path,
                    ))
        return candidates

    @staticmethod
    def _match_validation_field(
        explicit_field: Optional[str],
        message: str,
        candidates: Iterable[tuple[str, str, str]],
    ) -> Optional[str]:
        available = list(candidates)
        if explicit_field:
            exact = next(
                (path for path, _key, _label in available if path == explicit_field),
                None,
            )
            if exact:
                return exact
            by_key = [
                path for path, key, _label in available
                if key == explicit_field or path.endswith(f".{explicit_field}")
            ]
            if by_key:
                return by_key[0]

        normalized = message.casefold()
        # Prefer the longest label/key so that, for example, "Тип канала" is
        # selected before a shorter generic field name.
        searchable = sorted(
            available,
            key=lambda candidate: max(len(candidate[1]), len(candidate[2])),
            reverse=True,
        )
        for path, key, label in searchable:
            if label and label.casefold() in normalized:
                return path
            key_pattern = rf"(?<![\w.]){re.escape(key.casefold())}(?![\w.])"
            if re.search(key_pattern, normalized):
                return path
        return None

    @staticmethod
    def _ensure_environment(environment: str) -> None:
        if environment not in ENVIRONMENT_MAP:
            raise ValueError(f"Неизвестное окружение {environment!r}")

    @staticmethod
    def _check_version(form: BaseForm, requested: str) -> None:
        current = form_version(form)
        if requested and requested != current:
            raise FormVersionConflict(
                "Описание формы изменилось. Обновите страницу перед продолжением."
            )

    @staticmethod
    def _top_level_visible(
        fields: Iterable[FieldDefinition], key: str, values: Mapping[str, Any]
    ) -> bool:
        definitions = {field.key: field for field in fields}
        base = key
        match = _PLURAL_RE.match(key)
        if match and match.group(1) in definitions:
            base = match.group(1)
        field = definitions.get(base)
        return bool(field and _visible(field, values))

    @staticmethod
    def _find_field(fields: Iterable[FieldDefinition], path: str) -> FieldDefinition:
        return FormRuntime._find_field_context(fields, path)[0]

    @staticmethod
    def _find_field_context(
        fields: Iterable[FieldDefinition], path: str
    ) -> tuple[FieldDefinition, tuple[FieldDefinition, ...]]:
        parts = [part for part in path.split(".") if part]
        current = tuple(fields)
        found: Optional[FieldDefinition] = None
        siblings: tuple[FieldDefinition, ...] = current
        for index, part in enumerate(parts):
            siblings = current
            found = next((field for field in current if field.key == part), None)
            if found is None:
                match = _PLURAL_RE.match(part)
                if match is not None:
                    candidate = next(
                        (
                            field for field in current
                            if field.key == match.group(1) and field.plural
                        ),
                        None,
                    )
                    found = candidate
            if found is None:
                raise FormNotFoundError(path)
            if index < len(parts) - 1:
                if found.field_type != FieldType.BLOCK:
                    raise FormNotFoundError(path)
                current = tuple(found.block_fields)
        if found is None:
            raise FormNotFoundError(path)
        return found, siblings
