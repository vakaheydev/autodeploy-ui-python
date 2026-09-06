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
from typing import Any, Iterable, Mapping, Optional

from config.categories import CATEGORIES
from config.environments import ENVIRONMENT_MAP
from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from forms.registry import FormRegistry
from opencode_integration.context_builder import is_secret_key


_log = logging.getLogger("web.forms")
_PLURAL_RE = re.compile(r"^(.+)_(\d+)$")
_INLINE_REFERENCE_MAX_ITEMS = 99
_INLINE_REFERENCE_MAX_BYTES = 64 * 1024


class FormNotFoundError(KeyError):
    pass


class FormVersionConflict(ValueError):
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

    def __init__(self, selected: Mapping[str, list[dict[str, Any]]]) -> None:
        self._selected = selected

    def get_field_item(self, key: str) -> Optional[dict[str, Any]]:
        values = self._selected.get(key, [])
        return copy.deepcopy(values[0]) if values else None

    def get_field_items(self, key: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self._selected.get(key, []))

    def apply_form_data(self, _data: Mapping[str, Any]) -> list[str]:
        raise RuntimeError("apply_form_data недоступен во время server-side submit")


class FormRuntime:
    def __init__(self, container: Any) -> None:
        self.container = container

    def get_form(self, form_id: str) -> BaseForm:
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
        return form

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
        values = [form.form_id, form.title, form.category, CATEGORIES.get(form.category, "")]

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
        form = self.get_form(form_id)
        current = self._with_defaults(form.fields, dict(values or {}))
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
                }
                for action in form.get_server_actions()
            ] + [
                {
                    "id": f"legacy-{index}",
                    "label": button.label,
                    "available": False,
                    "reason": "Tkinter callback необходимо перенести в server action hook",
                    "style": button.style,
                    "confirmation_required": False,
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
        form = self.get_form(form_id)
        self._check_version(form, version)
        action = next(
            (item for item in form.get_server_actions() if item.action_id == action_id),
            None,
        )
        if action is None:
            raise FormNotFoundError(action_id)
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
        result = action.handler(environment, copy.deepcopy(validation.values))
        if result is None:
            result = {}
        if not isinstance(result, Mapping):
            result = {"data": result}
        proposed = result.get("values", {})
        if proposed is not None and not isinstance(proposed, Mapping):
            raise ValueError("Server action values должен быть объектом")
        return {
            "success": True,
            "message": str(result.get("message", "Действие выполнено")),
            "values": _json_safe(dict(proposed or {})),
            "data": _json_safe(result.get("data")),
        }

    def _field_document(
        self,
        form: BaseForm,
        field: FieldDefinition,
        environment: str,
        values: Mapping[str, Any],
        *,
        prefix: str = "",
        siblings: Optional[Iterable[FieldDefinition]] = None,
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
            "default": _json_safe(field.default),
            "hint": field.hint,
            "file_type": field.file_type,
            "width": field.width,
            "plural": field.plural,
            "plural_max": field.plural_max,
            "depends_on": field.depends_on or None,
            "depends_on_field": field.depends_on_field or None,
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
                "endpoint": f"/api/v1/forms/{form.form_id}/fields/{path}/options",
            }
            if ref.source == "local" and visible:
                items = self._resolve_reference(
                    field, environment, values, siblings=siblings
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
            block_values = values.get(field.key)
            nested_values = block_values if isinstance(block_values, Mapping) else {}
            document["fields"] = [
                self._field_document(
                    form,
                    nested,
                    environment,
                    nested_values,
                    prefix=path,
                    siblings=field.block_fields,
                )
                for nested in field.block_fields
            ]
        return document

    def state(
        self, form_id: str, environment: str, values: Mapping[str, Any], version: str = ""
    ) -> dict[str, Any]:
        form = self.get_form(form_id)
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
        form = self.get_form(form_id)
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
            for message in domain_errors:
                clean = str(message)
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
                        "field": None,
                        "code": "domain_validation",
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
        form = self.get_form(form_id)
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
        form = self.get_form(form_id)
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
        form = self.get_form(state.form_id)
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

    def fetch_ticket(self, form_id: str, environment: str, ticket_id: str) -> dict[str, Any]:
        self._ensure_environment(environment)
        form = self.get_form(form_id)
        if not form.itsm_support:
            raise ValueError("Эта форма не поддерживает прямое заполнение из ITSM")
        result = form.fetch_from_itsm(environment, ticket_id)
        if not isinstance(result, Mapping):
            raise ValueError("ITSM hook формы должен вернуть объект field_key -> value")
        validation = self.validate(
            form_id,
            environment,
            dict(result),
            form_version(form),
            validate_references=False,
        )
        return {
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
        form = self.get_form(form_id)
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
        if kind == "api":
            reference = ReferenceConfig(
                source="local",
                resource="gravitee_apis.json",
                value_key="id",
                label_key="name",
                search_keys=("name", "context_path", "id"),
            )
        elif kind == "application":
            reference = ReferenceConfig(
                source="http",
                resource="applications",
                value_key="id",
                label_key="name",
                search_keys=("name", "azp", "id"),
            )
        else:
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
                    "item": _public_item(item, reference),
                })
                if len(result) >= limit:
                    return {"items": result, "truncated": True}
        return {"items": result, "truncated": False}

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
        if field.field_type in {FieldType.TEXT, FieldType.TEXTAREA, FieldType.FILE, FieldType.SELECT}:
            if isinstance(value, (dict, list, tuple, set)):
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
                    field.block_fields, value, environment, errors, prefix=path
                )
                continue
            if field.reference is None or self._empty(value):
                continue
            items = self._resolve_reference(
                field, environment, values, siblings=field_definitions
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
    ) -> dict[str, list[dict[str, Any]]]:
        selected: dict[str, list[dict[str, Any]]] = {}
        field_definitions = tuple(fields)
        for field in field_definitions:
            value = values.get(field.key)
            if field.field_type == FieldType.BLOCK and isinstance(value, Mapping):
                selected.update(self._selected_reference_items(
                    field.block_fields, value, environment, resolver
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
    ) -> Optional[dict[str, Any]]:
        if not field.depends_on:
            return None
        parent_value = values.get(field.depends_on)
        if field.depends_on_field:
            if isinstance(parent_value, Mapping):
                parent_value = parent_value.get(field.depends_on_field)
            elif not self._empty(parent_value):
                parent = next(
                    (item for item in siblings if item.key == field.depends_on),
                    None,
                )
                if parent is None or parent.reference is None:
                    parent_value = None
                else:
                    parent_items = self._resolve_reference(
                        parent,
                        environment,
                        values,
                        siblings=siblings,
                        resolver=resolver,
                    )
                    selected = next((
                        item for item in parent_items
                        if str(item.get(parent.reference.value_key, ""))
                        == str(parent_value)
                    ), None)
                    parent_value = (
                        selected.get(field.depends_on_field)
                        if selected is not None
                        else None
                    )
        return (
            {field.depends_on: parent_value}
            if not self._empty(parent_value)
            else None
        )

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

    @staticmethod
    def _with_defaults(fields: Iterable[FieldDefinition], values: dict[str, Any]) -> dict[str, Any]:
        result = dict(values)
        for field in fields:
            if field.key not in result and field.default is not None:
                result[field.key] = copy.deepcopy(field.default)
        return result

    @staticmethod
    def _empty(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    @staticmethod
    def _error(field: Optional[str], code: str, message: str) -> dict[str, Any]:
        return {"field": field, "code": code, "message": message}

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
                raise FormNotFoundError(path)
            if index < len(parts) - 1:
                if found.field_type != FieldType.BLOCK:
                    raise FormNotFoundError(path)
                current = tuple(found.block_fields)
        if found is None:
            raise FormNotFoundError(path)
        return found, siblings
