"""Построение строгой JSON Schema из декларативного описания формы."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Optional

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType

CONFIDENCE_VALUES = ("high", "medium", "low", "unknown")
DEFAULT_STRING_MAX_LENGTH = 4000
TEXTAREA_MAX_LENGTH = 30000
FILE_CONTENT_MAX_LENGTH = 100000
MAX_MULTISELECT_ITEMS = 100


def _nullable(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Добавляет null, сохраняя ограничения исходного типа."""
    return {"anyOf": [schema, {"type": "null"}]}


def _string_schema(field: FieldDefinition) -> Dict[str, Any]:
    max_length = DEFAULT_STRING_MAX_LENGTH
    if field.field_type == FieldType.TEXTAREA:
        max_length = TEXTAREA_MAX_LENGTH
    elif field.field_type == FieldType.FILE:
        max_length = FILE_CONTENT_MAX_LENGTH

    result: Dict[str, Any] = {
        "type": "string",
        "minLength": 1,
        "maxLength": max_length,
        "description": field.hint or field.placeholder or field.label,
    }
    if field.field_type == FieldType.TEXT:
        result["pattern"] = r"^[^\r\n]*$"
    key = field.key.lower()
    if key.endswith("_url") or key == "url":
        result["format"] = "uri"
        result["pattern"] = r"^https?://[^\s]+$"
    if key in {"context_path", "base_path"}:
        result["pattern"] = r"^/[^\s]*$"
    return result


def _reference_enum(
    field: FieldDefinition,
    reference_values: Mapping[str, Iterable[Any]],
) -> list[Any]:
    values = []
    seen = set()
    for value in reference_values.get(field.key, ()):
        if value is None:
            continue
        normalized = str(value)
        if normalized not in seen:
            seen.add(normalized)
            values.append(normalized)
    return values


def field_value_schema(
    field: FieldDefinition,
    reference_values: Optional[Mapping[str, Iterable[Any]]] = None,
    *,
    strict_references: bool = False,
) -> Dict[str, Any]:
    """Возвращает nullable-схему значения одного поля."""
    references = reference_values or {}
    if field.field_type in (FieldType.TEXT, FieldType.TEXTAREA, FieldType.FILE):
        return _nullable(_string_schema(field))

    if field.field_type == FieldType.NUMBER:
        return _nullable({
            "type": "integer",
            "minimum": 0,
            "maximum": 1_000_000_000,
            "description": field.hint or field.label,
        })

    if field.field_type == FieldType.CHECKBOX:
        return {"type": ["boolean", "null"], "description": field.hint or field.label}

    if field.field_type == FieldType.SELECT:
        values = _reference_enum(field, references)
        # Финальная локальная валидация допускает только подтверждённые ID. До
        # загрузки справочника модель возвращает смысловое имя/метку, не ID.
        if field.reference is not None and strict_references and not values:
            return {
                "type": "null",
                "description": (
                    f"{field.hint or field.label}. Reference values are unavailable; "
                    "the only allowed value is null."
                ),
            }
        value_schema: Dict[str, Any] = {
            "type": "string",
            "minLength": 1,
            "maxLength": DEFAULT_STRING_MAX_LENGTH,
            "description": (
                (field.hint or field.label)
                + (
                    ". Return a semantic label explicitly supported by the context; "
                    "the application resolves it to a reference ID locally."
                    if field.reference is not None and not values
                    else ""
                )
            ),
        }
        if values:
            value_schema["enum"] = values
        return _nullable(value_schema)

    if field.field_type == FieldType.MULTISELECT:
        values = _reference_enum(field, references)
        if field.reference is not None and strict_references and not values:
            return {
                "type": "null",
                "description": (
                    f"{field.hint or field.label}. Reference values are unavailable; "
                    "the only allowed value is null."
                ),
            }
        item_schema: Dict[str, Any] = {
            "type": "string",
            "minLength": 1,
            "maxLength": DEFAULT_STRING_MAX_LENGTH,
        }
        if values:
            item_schema["enum"] = values
        return _nullable({
            "type": "array",
            "items": item_schema,
            "uniqueItems": True,
            "maxItems": MAX_MULTISELECT_ITEMS,
            "description": (
                (field.hint or field.label)
                + (
                    ". Return semantic labels explicitly supported by the context; "
                    "the application resolves them to reference IDs locally."
                    if field.reference is not None and not values
                    else ""
                )
            ),
        })

    if field.field_type == FieldType.BLOCK:
        nested_props = {
            sub.key: field_value_schema(
                sub,
                references,
                strict_references=strict_references,
            )
            for sub in field.block_fields
        }
        return _nullable({
            "type": "object",
            "additionalProperties": False,
            "required": list(nested_props),
            "properties": nested_props,
            "description": field.hint or field.label,
        })

    raise ValueError(f"Неподдерживаемый тип поля: {field.field_type}")


def build_form_schema(
    form: BaseForm,
    reference_values: Optional[Mapping[str, Iterable[Any]]] = None,
    *,
    strict_references: bool = False,
) -> Dict[str, Any]:
    """Строит корневой контракт ``{form, meta}`` для одной формы."""
    fields = list(form.fields)
    form_properties = {
        field.key: field_value_schema(
            field,
            reference_values,
            strict_references=strict_references,
        )
        for field in fields
    }
    field_keys = list(form_properties)

    source_properties = {
        key: _nullable({
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": f"Source path for {key}",
        })
        for key in field_keys
    }
    confidence_properties = {
        key: {
            "type": "string",
            "enum": list(CONFIDENCE_VALUES),
            "description": f"Extraction confidence for {key}",
        }
        for key in field_keys
    }
    reason_properties = {
        key: _nullable({
            "type": "string",
            "minLength": 1,
            "maxLength": 1000,
            "description": f"Missing value, uncertainty or conflict reason for {key}",
        })
        for key in field_keys
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"AI autofill result for {form.form_id}",
        "type": "object",
        "additionalProperties": False,
        "required": ["form", "meta"],
        "properties": {
            "form": {
                "type": "object",
                "additionalProperties": False,
                # Каждое поле присутствует; неизвестное значение выражается null.
                "required": field_keys,
                "properties": form_properties,
            },
            "meta": {
                "type": "object",
                "additionalProperties": False,
                "required": ["warnings", "sources", "confidence", "reasons", "conflicts"],
                "properties": {
                    "warnings": {
                        "type": "array",
                        "items": {
                            "type": "string", "minLength": 1, "maxLength": 1000,
                        },
                        "maxItems": 100,
                    },
                    "sources": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": field_keys,
                        "properties": source_properties,
                    },
                    "confidence": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": field_keys,
                        "properties": confidence_properties,
                    },
                    "reasons": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": field_keys,
                        "properties": reason_properties,
                    },
                    "conflicts": {
                        "type": "array",
                        "maxItems": 100,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["field", "message", "sources"],
                            "properties": {
                                "field": {"type": "string", "enum": field_keys},
                                "message": {
                                    "type": "string", "minLength": 1, "maxLength": 1000,
                                },
                                "sources": {
                                    "type": "array",
                                    "items": {
                                        "type": "string", "minLength": 1, "maxLength": 500,
                                    },
                                    "minItems": 1,
                                    "maxItems": 20,
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def describe_form(form: BaseForm, environment: str) -> Dict[str, Any]:
    """Компактное доверенное описание формы для prompt."""
    def json_safe_default(value: Any) -> Any:
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            return str(value)[:500]
        return value

    def describe_field(field: FieldDefinition) -> Dict[str, Any]:
        description: Dict[str, Any] = {
            "key": field.key,
            "label": field.label,
            "type": field.field_type.value,
            "required_in_final_form": field.required,
            "hint": field.hint,
            "placeholder": field.placeholder,
            "default": json_safe_default(field.default),
            "conditional": field.condition is not None,
            "depends_on": field.depends_on or None,
            "file_type": field.file_type or None,
            "plural": field.plural,
            "plural_max": field.plural_max,
            "reference_backed": field.reference is not None,
        }
        if field.block_fields:
            description["fields"] = [describe_field(item) for item in field.block_fields]
        return description

    return {
        "form_id": form.form_id,
        "title": form.title,
        "environment": environment,
        "fields": [describe_field(field) for field in form.fields],
    }
