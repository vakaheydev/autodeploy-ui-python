"""Независимая повторная валидация AI JSON-ответа на стороне Python."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional

from forms.base_form import BaseForm
from forms.fields import FieldType
from opencode_integration.schemas import build_form_schema, field_value_schema

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover - окружение пользователя
    jsonschema = None  # type: ignore[assignment]
    _JSONSCHEMA_IMPORT_ERROR = exc
else:
    _JSONSCHEMA_IMPORT_ERROR = None


class ResponseValidationError(ValueError):
    """Ответ модели нельзя показывать или применять."""

    def __init__(self, issues: Iterable[str]) -> None:
        self.issues = list(issues)
        super().__init__("\n".join(self.issues))


@dataclass(frozen=True)
class PreviewField:
    key: str
    label: str
    field_type: FieldType
    current_value: Any
    proposed_value: Any
    confidence: str
    source: Optional[str]
    reason: Optional[str]
    conflict: Optional[str] = None
    candidates: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ValidatedResponse:
    payload: Dict[str, Any]
    preview_fields: list[PreviewField]
    warnings: list[str] = field(default_factory=list)
    reference_candidates: Dict[str, tuple[tuple[str, str], ...]] = field(
        default_factory=dict
    )

    @property
    def form_data(self) -> Dict[str, Any]:
        return self.payload["form"]

    @property
    def meta(self) -> Dict[str, Any]:
        return self.payload["meta"]


def _require_jsonschema() -> None:
    if jsonschema is None:
        raise RuntimeError(
            "Для AI-автозаполнения требуется пакет jsonschema. "
            "Установите зависимости из requirements.txt."
        ) from _JSONSCHEMA_IMPORT_ERROR


def _json_path(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    return path or "$"


def _schema_errors(instance: Any, schema: Dict[str, Any]) -> list[str]:
    _require_jsonschema()
    # Старые корпоративные Python-сборки могут содержать jsonschema 3.x.
    # Используем Draft 2020-12 при наличии; применяемый нами поднабор keywords
    # (anyOf, additionalProperties, enum, limits) также поддерживается Draft 7.
    validator_class = getattr(
        jsonschema,  # type: ignore[arg-type]
        "Draft202012Validator",
        jsonschema.Draft7Validator,  # type: ignore[union-attr]
    )
    validator = validator_class(
        schema,
        format_checker=jsonschema.FormatChecker(),  # type: ignore[union-attr]
    )
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
    return [f"{_json_path(error)}: {error.message}" for error in errors]


def _decode(payload: Any) -> Any:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ResponseValidationError([f"Невалидный JSON: {exc}"]) from exc
    return payload


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


class ResponseValidator:
    """Проверяет schema и зависимые поля, готовит preview."""

    def validate(
        self,
        payload: Any,
        *,
        form: BaseForm,
        current_values: Optional[Mapping[str, Any]] = None,
        reference_values: Optional[Mapping[str, Iterable[Any]]] = None,
        schema: Optional[Dict[str, Any]] = None,
        reference_candidates: Optional[
            Mapping[str, Iterable[tuple[str, str]]]
        ] = None,
        check_domain: bool = True,
    ) -> ValidatedResponse:
        decoded = _decode(payload)
        effective_schema = schema or build_form_schema(form, reference_values)
        issues = _schema_errors(decoded, effective_schema)
        if issues:
            raise ResponseValidationError(issues)
        assert isinstance(decoded, dict)  # подтверждено schema

        domain_values = dict(current_values or {})
        domain_values.update({
            key: value
            for key, value in decoded["form"].items()
            if value is not None
        })
        domain_issues = (
            self._domain_issues(domain_values, form) if check_domain else []
        )
        domain_issues.extend(self._metadata_issues(decoded, form))
        if domain_issues:
            raise ResponseValidationError(domain_issues)

        current = dict(current_values or {})
        meta = decoded["meta"]
        conflicts_by_field: Dict[str, list[str]] = {}
        for conflict in meta["conflicts"]:
            conflicts_by_field.setdefault(conflict["field"], []).append(conflict["message"])

        rows = [
            PreviewField(
                key=field_def.key,
                label=field_def.label,
                field_type=field_def.field_type,
                current_value=current.get(field_def.key),
                proposed_value=decoded["form"][field_def.key],
                confidence=meta["confidence"][field_def.key],
                source=meta["sources"][field_def.key],
                reason=meta["reasons"][field_def.key],
                conflict="; ".join(conflicts_by_field.get(field_def.key, [])) or None,
                candidates=tuple((reference_candidates or {}).get(field_def.key, ())),
            )
            for field_def in form.fields
        ]

        warnings = list(meta["warnings"])
        low_fields = [row.label for row in rows if row.confidence == "low"]
        if low_fields:
            warnings.append(
                "Низкая уверенность — проверьте перед применением: " + ", ".join(low_fields)
            )
        return ValidatedResponse(
            copy.deepcopy(decoded),
            rows,
            warnings,
            {
                key: tuple(items)
                for key, items in (reference_candidates or {}).items()
            },
        )

    def validate_manual_values(
        self,
        values: Mapping[str, Any],
        *,
        form: BaseForm,
        reference_values: Optional[Mapping[str, Iterable[Any]]] = None,
        check_domain: bool = True,
    ) -> Dict[str, list[str]]:
        """Проверяет отредактированные предложения по полям для preview."""
        result: Dict[str, list[str]] = {}
        fields = {item.key: item for item in form.fields}
        for key, value in values.items():
            field_def = fields.get(key)
            if field_def is None:
                result[key] = ["Неизвестное поле"]
                continue
            errors = _schema_errors(
                value,
                field_value_schema(
                    field_def,
                    reference_values,
                    strict_references=True,
                ),
            )
            if errors:
                result[key] = errors

        if check_domain:
            self._merge_domain_errors(result, values, form)
        return result

    def validate_domain_values(
        self,
        values: Mapping[str, Any],
        *,
        form: BaseForm,
    ) -> Dict[str, list[str]]:
        result: Dict[str, list[str]] = {}
        self._merge_domain_errors(result, values, form)
        return result

    @classmethod
    def _merge_domain_errors(
        cls,
        target: Dict[str, list[str]],
        values: Mapping[str, Any],
        form: BaseForm,
    ) -> None:
        # Structured AI output may legitimately contain null for an unknown
        # required field. В ручном preview уже проверяем effective form: если
        # пользователь явно очищает обязательное поле, применять это нельзя.
        for field_def in form.fields:
            if field_def.required and _is_empty(values.get(field_def.key)):
                target.setdefault(field_def.key, []).append(
                    f"Поле «{field_def.label}» обязательно для заполнения"
                )
        try:
            form_issues = form.validate(dict(values))
        except Exception as exc:
            form_issues = [
                f"Ошибка проверки правил формы ({type(exc).__name__})"
            ]
        for message in form_issues:
            text = str(message)[:1000]
            # BaseForm required-проверку выше делаем точнее для списков/объектов.
            if text.startswith('Поле "') and "обязательно для заполнения" in text:
                continue
            lowered = text.casefold()
            field_key = next(
                (
                    field_def.key
                    for field_def in form.fields
                    if field_def.label.casefold() in lowered
                ),
                "__form__",
            )
            messages = target.setdefault(field_key, [])
            if text not in messages:
                messages.append(text)
        for issue in cls._domain_issues(dict(values), form):
            key, _, message = issue.partition(":")
            target.setdefault(key, []).append(message.strip() or issue)

    @staticmethod
    def _domain_issues(values: Mapping[str, Any], form: BaseForm) -> list[str]:
        issues: list[str] = []
        for field_def in form.fields:
            value = values.get(field_def.key)
            if (
                field_def.key.lower() in {"context_path", "base_path"}
                and isinstance(value, str)
                and value
            ):
                segments = value.split("/")
                if "\\" in value or "//" in value or ".." in segments:
                    issues.append(
                        f"{field_def.key}: путь содержит недопустимый сегмент"
                    )
            if (
                field_def.field_type == FieldType.FILE
                and field_def.file_type.lower() == ".json"
                and isinstance(value, str)
                and value.strip()
            ):
                try:
                    json.loads(value)
                except json.JSONDecodeError:
                    issues.append(f"{field_def.key}: содержимое не является валидным JSON")
            if field_def.depends_on and not _is_empty(value):
                if _is_empty(values.get(field_def.depends_on)):
                    issues.append(
                        f"{field_def.key}: задано зависимое поле без {field_def.depends_on}"
                    )
            if field_def.condition is not None and not _is_empty(value):
                try:
                    visible = bool(field_def.condition(dict(values)))
                except Exception as exc:
                    issues.append(f"{field_def.key}: ошибка проверки зависимости ({type(exc).__name__})")
                    continue
                if not visible:
                    issues.append(
                        f"{field_def.key}: значение задано для скрытого условного поля"
                    )
        return issues

    @staticmethod
    def _metadata_issues(payload: Mapping[str, Any], form: BaseForm) -> list[str]:
        """Проверяет согласованность значения с source/confidence/reason."""
        values = payload["form"]
        meta = payload["meta"]
        issues: list[str] = []
        for field_def in form.fields:
            key = field_def.key
            value = values[key]
            source = meta["sources"][key]
            confidence = meta["confidence"][key]
            reason = meta["reasons"][key]
            if value is None:
                if not isinstance(reason, str) or not reason.strip():
                    issues.append(
                        f"meta.reasons.{key}: для отсутствующего значения нужна причина"
                    )
                if confidence != "unknown":
                    issues.append(
                        f"meta.confidence.{key}: для null ожидается unknown"
                    )
            elif not isinstance(source, str) or not source.strip():
                issues.append(
                    f"meta.sources.{key}: для извлечённого значения нужен источник"
                )
        return issues


def parse_edited_value(raw: str, field_type: FieldType) -> Any:
    """Преобразует текст preview обратно в тип существующего FieldWidget."""
    text = raw.strip()
    if not text:
        return None
    if field_type == FieldType.NUMBER:
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError("Ожидается целое число") from exc
    if field_type == FieldType.CHECKBOX:
        normalized = text.lower()
        if normalized in {"true", "1", "yes", "да"}:
            return True
        if normalized in {"false", "0", "no", "нет"}:
            return False
        raise ValueError("Ожидается true или false")
    if field_type in (FieldType.MULTISELECT, FieldType.BLOCK):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            expected = "JSON-массив" if field_type == FieldType.MULTISELECT else "JSON-объект"
            raise ValueError(f"Ожидается {expected}: {exc.msg}") from exc
        return value
    return raw


def display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
