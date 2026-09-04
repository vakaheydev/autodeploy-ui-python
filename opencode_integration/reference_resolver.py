"""Локальное сопоставление смысловых AI-кандидатов с ID справочников."""
from __future__ import annotations

import copy
import difflib
import json
import logging
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from opencode_integration.client import OpenCodeCancelled

_log = logging.getLogger("opencode.references")


DEFAULT_INLINE_REFERENCE_MAX_ITEMS = 99
DEFAULT_INLINE_REFERENCE_MAX_BYTES = 24 * 1024
DEFAULT_INLINE_REFERENCE_TOTAL_BYTES = 48 * 1024


@dataclass(frozen=True)
class ReferenceCandidate:
    value: str
    label: str
    score: float


@dataclass(frozen=True)
class ReferenceResolutionResult:
    payload: Dict[str, Any]
    reference_values: Dict[str, list[str]]
    candidates: Dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InlineReferenceCatalog:
    """Безопасная компактная проекция справочников для доверенного prompt."""

    fields: Dict[str, Dict[str, Any]]
    reference_values: Dict[str, list[str]]
    total_bytes: int = 0


@dataclass(frozen=True)
class _Match:
    value: Optional[str]
    candidates: tuple[ReferenceCandidate, ...]
    exact: bool = False
    ambiguous: bool = False


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


class LocalReferenceResolver:
    """Сопоставляет reference-поля и готовит малые полные enum для OpenCode."""

    def __init__(self, resolver: Any, *, candidate_limit: int = 5) -> None:
        self._resolver = resolver
        self._candidate_limit = max(1, min(20, int(candidate_limit)))

    def build_inline_catalog(
        self,
        *,
        form: BaseForm,
        environment: str,
        current_values: Optional[Mapping[str, Any]] = None,
        max_items: int = DEFAULT_INLINE_REFERENCE_MAX_ITEMS,
        max_bytes: int = DEFAULT_INLINE_REFERENCE_MAX_BYTES,
        total_bytes: int = DEFAULT_INLINE_REFERENCE_TOTAL_BYTES,
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> InlineReferenceCatalog:
        """Встраивает только доказанно полный и компактный справочник.

        Размер считается по UTF-8 представлению нормализованной компактной JSON
        проекции. Исходные записи не передаются: только value, label и aliases.
        Лимит количества включительный сверху, поэтому значение по умолчанию 99
        реализует правило «меньше 100 элементов».
        """
        item_limit = max(1, min(10_000, int(max_items)))
        field_byte_limit = max(256, min(2 * 1024 * 1024, int(max_bytes)))
        total_byte_limit = max(256, min(4 * 1024 * 1024, int(total_bytes)))
        effective = dict(current_values or {})
        for field_def in form.fields:
            if (
                effective.get(field_def.key) in (None, "", [], {})
                and field_def.default not in (None, "", [], {})
            ):
                effective[field_def.key] = field_def.default

        notify = on_progress or (lambda _message: None)
        policies: Dict[str, Dict[str, Any]] = {}
        candidates: list[
            tuple[int, tuple[str, ...], FieldDefinition, list[Dict[str, Any]], int]
        ] = []

        for index, (path, field_def) in enumerate(self._reference_fields(form.fields)):
            self._check_cancel(cancel_event)
            display_key = ".".join(path)
            reference = field_def.reference
            assert reference is not None
            base: Dict[str, Any] = {
                "source": reference.source,
                "resource": reference.resource,
                "resolution": "python_after_extraction",
                "options_complete": False,
            }
            missing = self._missing_dependencies(field_def, effective)
            if missing:
                policies[display_key] = {
                    **base,
                    "reason": "dependency_unresolved",
                    "required_parameters": list(missing),
                    "instruction": (
                        "Return the exact semantic value requested by the operator; "
                        "Python resolves it after dependent fields are known."
                    ),
                }
                continue

            notify(f"Проверяю размер справочника: {field_def.label}…")
            items, load_error = self._load_items(
                field_def,
                environment=environment,
                effective=effective,
            )
            if load_error:
                policies[display_key] = {
                    **base,
                    "reason": "catalog_unavailable",
                    "instruction": (
                        "Return the exact semantic value from the request or null; "
                        "Python will try to resolve it later."
                    ),
                }
                continue

            options = self._project_options(items, reference)
            serialized_bytes = self._serialized_catalog_size(display_key, options)
            details = {
                "item_count": len(options),
                "serialized_bytes": serialized_bytes,
            }
            if not options:
                policies[display_key] = {
                    **base,
                    **details,
                    "reason": "catalog_empty",
                    "instruction": "Return null because the catalog has no options.",
                }
            elif len(options) > item_limit:
                policies[display_key] = {
                    **base,
                    **details,
                    "reason": "item_limit_exceeded",
                    "instruction": (
                        "Return the exact semantic value requested by the operator; "
                        "Python resolves it against the full catalog."
                    ),
                }
            elif serialized_bytes > field_byte_limit:
                policies[display_key] = {
                    **base,
                    **details,
                    "reason": "field_byte_limit_exceeded",
                    "instruction": (
                        "Return the exact semantic value requested by the operator; "
                        "Python resolves it against the full catalog."
                    ),
                }
            else:
                candidates.append((index, path, field_def, options, serialized_bytes))

        # При дефиците общего бюджета сначала сохраняем обязательные и
        # безусловные поля; внутри группы остаётся порядок формы.
        candidates.sort(key=lambda item: (
            not item[2].required,
            item[2].condition is not None,
            item[0],
        ))
        used_bytes = 0
        reference_values: Dict[str, list[str]] = {}
        for _index, path, field_def, options, serialized_bytes in candidates:
            display_key = ".".join(path)
            reference = field_def.reference
            assert reference is not None
            base = {
                "source": reference.source,
                "resource": reference.resource,
                "item_count": len(options),
                "serialized_bytes": serialized_bytes,
            }
            if used_bytes + serialized_bytes > total_byte_limit:
                policies[display_key] = {
                    **base,
                    "resolution": "python_after_extraction",
                    "options_complete": False,
                    "reason": "total_byte_limit_exceeded",
                    "instruction": (
                        "Return the exact semantic value requested by the operator; "
                        "Python resolves it against the full catalog."
                    ),
                }
                continue
            used_bytes += serialized_bytes
            policies[display_key] = {
                **base,
                "resolution": "inline_enum",
                "options_complete": True,
                "instruction": (
                    "Choose only option.value. Never query MCP to enumerate, "
                    "validate, or replace this complete catalog."
                ),
                "options": options,
            }
            # schemas.py индексирует nested reference по leaf key.
            reference_values[field_def.key] = [
                str(option["value"]) for option in options
            ]

        ordered_policies = {
            ".".join(path): policies[".".join(path)]
            for path, _field_def in self._reference_fields(form.fields)
        }
        _log.info(
            "inline reference catalog fields=%d inline=%d bytes=%d "
            "max_items=%d max_field_bytes=%d max_total_bytes=%d",
            len(ordered_policies),
            len(reference_values),
            used_bytes,
            item_limit,
            field_byte_limit,
            total_byte_limit,
        )
        return InlineReferenceCatalog(
            fields=ordered_policies,
            reference_values=reference_values,
            total_bytes=used_bytes,
        )

    def resolve(
        self,
        payload: Mapping[str, Any],
        *,
        form: BaseForm,
        environment: str,
        current_values: Optional[Mapping[str, Any]] = None,
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> ReferenceResolutionResult:
        result = copy.deepcopy(dict(payload))
        form_values = result["form"]
        meta = result["meta"]
        effective = dict(current_values or {})
        effective.update({
            key: value
            for key, value in form_values.items()
            if value is not None
        })
        reference_values: Dict[str, list[str]] = {}
        candidates: Dict[str, tuple[tuple[str, str], ...]] = {}
        warnings: list[str] = []
        notify = on_progress or (lambda _message: None)

        for path, field_def in self._reference_fields(form.fields):
            self._check_cancel(cancel_event)
            display_key = ".".join(path)
            notify(f"Сопоставляю справочник: {field_def.label}…")
            query = self._get_path(form_values, path)
            items, load_error = self._load_items(
                field_def,
                environment=environment,
                effective=effective,
            )
            allowed = self._allowed_values(items, field_def.reference)
            # schemas.py индексирует nested reference по leaf key.
            reference_values[field_def.key] = allowed
            if load_error:
                warnings.append(
                    f"{field_def.label}: справочник недоступен ({load_error})"
                )
            if query is None:
                continue

            if field_def.field_type == FieldType.SELECT:
                match = self._match_one(query, items, field_def.reference)
                candidates[display_key] = self._candidate_pairs(match.candidates)
                if len(path) == 1:
                    candidates[path[0]] = candidates[display_key]
                if match.value is None:
                    self._set_path(form_values, path, None)
                    self._mark_unresolved(
                        meta,
                        path[0],
                        field_def.label,
                        query,
                        match,
                    )
                    warnings.append(
                        self._unresolved_warning(field_def.label, query, match)
                    )
                else:
                    self._set_path(form_values, path, match.value)
                    effective[path[-1]] = match.value
                    effective[path[0]] = (
                        form_values[path[0]]
                        if len(path) == 1
                        else effective.get(path[0])
                    )
                    if not match.exact:
                        self._cap_confidence(meta, path[0], "medium")
                        self._append_reason(
                            meta,
                            path[0],
                            f"Справочник локально сопоставлен по похожему имени "
                            f"{query!r} → {match.value!r}.",
                        )

            elif field_def.field_type == FieldType.MULTISELECT:
                queries = query if isinstance(query, list) else [query]
                resolved: list[str] = []
                unresolved: list[str] = []
                merged_candidates: list[ReferenceCandidate] = []
                fuzzy = False
                for item in queries:
                    match = self._match_one(item, items, field_def.reference)
                    merged_candidates.extend(match.candidates)
                    if match.value is None:
                        unresolved.append(str(item))
                    elif match.value not in resolved:
                        resolved.append(match.value)
                        fuzzy = fuzzy or not match.exact
                top = self._dedupe_candidates(merged_candidates)
                candidates[display_key] = self._candidate_pairs(top)
                if len(path) == 1:
                    candidates[path[0]] = candidates[display_key]
                self._set_path(form_values, path, resolved or None)
                effective[path[-1]] = resolved or None
                if unresolved:
                    if resolved:
                        self._cap_confidence(meta, path[0], "low")
                        self._append_reason(
                            meta,
                            path[0],
                            "Не сопоставлены значения: " + ", ".join(unresolved[:10]),
                        )
                    else:
                        self._mark_unresolved(
                            meta,
                            path[0],
                            field_def.label,
                            ", ".join(unresolved),
                            _Match(None, top),
                        )
                    warnings.append(
                        f"{field_def.label}: не сопоставлены локально: "
                        + ", ".join(unresolved[:10])
                    )
                elif fuzzy:
                    self._cap_confidence(meta, path[0], "medium")
                    self._append_reason(
                        meta,
                        path[0],
                        "Часть значений справочника сопоставлена по похожим именам.",
                    )

        unique_warnings = list(dict.fromkeys(item[:1000] for item in warnings))
        meta["warnings"] = list(
            dict.fromkeys([*meta.get("warnings", []), *unique_warnings])
        )[:100]
        _log.info(
            "reference resolution fields=%d warnings=%d catalog_values=%d",
            len(reference_values),
            len(unique_warnings),
            sum(len(values) for values in reference_values.values()),
        )
        return ReferenceResolutionResult(
            payload=result,
            reference_values=reference_values,
            candidates=candidates,
            warnings=unique_warnings,
        )

    def _load_items(
        self,
        field_def: FieldDefinition,
        *,
        environment: str,
        effective: Mapping[str, Any],
    ) -> tuple[list[Dict[str, Any]], str]:
        reference = field_def.reference
        assert reference is not None
        extra: Dict[str, Any] = {}
        required = reference.required_params or (
            (field_def.depends_on,) if field_def.depends_on else ()
        )
        for name in required:
            value = effective.get(name)
            if value in (None, "", [], {}):
                return [], f"не выбрано зависимое поле {name}"
            extra[name] = value
        try:
            raw = self._resolver.resolve(reference, environment, extra or None)
        except Exception as exc:
            _log.warning(
                "reference load failed field=%s resource=%s error_type=%s",
                field_def.key,
                reference.resource,
                type(exc).__name__,
            )
            return [], type(exc).__name__
        return (
            [item for item in raw if isinstance(item, dict)][:10_000],
            "",
        )

    @staticmethod
    def _missing_dependencies(
        field_def: FieldDefinition,
        effective: Mapping[str, Any],
    ) -> tuple[str, ...]:
        reference = field_def.reference
        assert reference is not None
        required = reference.required_params or (
            (field_def.depends_on,) if field_def.depends_on else ()
        )
        return tuple(
            name
            for name in required
            if effective.get(name) in (None, "", [], {})
        )

    @classmethod
    def _project_options(
        cls,
        items: Sequence[Mapping[str, Any]],
        reference: ReferenceConfig,
    ) -> list[Dict[str, Any]]:
        options: list[Dict[str, Any]] = []
        seen_values: set[str] = set()
        search_keys = tuple(dict.fromkeys(reference.search_keys))
        for item in items:
            raw_value = item.get(reference.value_key)
            if raw_value is None:
                continue
            value = cls._catalog_text(raw_value, max_length=4000, collapse=False)
            if not value or value in seen_values:
                continue
            seen_values.add(value)
            raw_label = item.get(reference.label_key, raw_value)
            label = cls._catalog_text(raw_label, max_length=4000, collapse=True)
            option: Dict[str, Any] = {"value": value, "label": label or value}
            aliases: list[str] = []
            for key in search_keys:
                raw_alias = item.get(key)
                if raw_alias in (None, ""):
                    continue
                alias = cls._catalog_text(raw_alias, max_length=500, collapse=True)
                if alias and alias not in (value, option["label"]) and alias not in aliases:
                    aliases.append(alias)
            if aliases:
                option["aliases"] = aliases
            options.append(option)
        return options

    @staticmethod
    def _catalog_text(value: Any, *, max_length: int, collapse: bool) -> str:
        text = unicodedata.normalize("NFKC", str(value)).strip()
        if collapse:
            text = " ".join(text.split())
        return text[:max_length]

    @staticmethod
    def _serialized_catalog_size(
        display_key: str,
        options: Sequence[Mapping[str, Any]],
    ) -> int:
        rendered = json.dumps(
            {"field": display_key, "options": options},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return len(rendered.encode("utf-8"))

    def _match_one(
        self,
        query: Any,
        items: Sequence[Mapping[str, Any]],
        reference: Optional[ReferenceConfig],
    ) -> _Match:
        if reference is None:
            return _Match(None, ())
        normalized_query = _normalize(query)
        if not normalized_query:
            return _Match(None, ())
        scored: list[ReferenceCandidate] = []
        exact_values: list[str] = []
        for item in items:
            raw_value = item.get(reference.value_key)
            if raw_value is None:
                continue
            value = str(raw_value)
            label = str(item.get(reference.label_key, value))
            search_keys = tuple(dict.fromkeys(
                (reference.value_key, reference.label_key, *reference.search_keys)
            ))
            texts = [
                _normalize(item.get(key))
                for key in search_keys
                if item.get(key) not in (None, "")
            ]
            if normalized_query in texts:
                exact_values.append(value)
                score = 1.0 if _normalize(value) == normalized_query else 0.99
            else:
                similarities = [
                    difflib.SequenceMatcher(None, normalized_query, text).ratio()
                    for text in texts
                    if text
                ]
                contains = any(
                    len(normalized_query) >= 4
                    and (
                        normalized_query in text
                        or text in normalized_query
                    )
                    for text in texts
                )
                score = max(similarities or [0.0])
                if contains:
                    score = max(score, 0.92)
            scored.append(ReferenceCandidate(value, label, score))

        ranked = self._dedupe_candidates(scored)
        visible = tuple(ranked[: self._candidate_limit])
        unique_exact = list(dict.fromkeys(exact_values))
        if len(unique_exact) == 1:
            return _Match(unique_exact[0], visible, exact=True)
        if len(unique_exact) > 1:
            return _Match(None, visible, exact=True, ambiguous=True)
        if not ranked or ranked[0].score < 0.88:
            return _Match(None, visible)
        gap = ranked[0].score - (ranked[1].score if len(ranked) > 1 else 0.0)
        if gap < 0.06:
            return _Match(None, visible, ambiguous=True)
        return _Match(ranked[0].value, visible, exact=False)

    @staticmethod
    def _dedupe_candidates(
        candidates: Iterable[ReferenceCandidate],
    ) -> tuple[ReferenceCandidate, ...]:
        best: Dict[str, ReferenceCandidate] = {}
        for candidate in candidates:
            current = best.get(candidate.value)
            if current is None or candidate.score > current.score:
                best[candidate.value] = candidate
        return tuple(
            sorted(best.values(), key=lambda item: (-item.score, item.label.casefold()))
        )

    @staticmethod
    def _allowed_values(
        items: Iterable[Mapping[str, Any]],
        reference: Optional[ReferenceConfig],
    ) -> list[str]:
        if reference is None:
            return []
        return list(dict.fromkeys(
            str(item[reference.value_key])
            for item in items
            if item.get(reference.value_key) is not None
        ))

    @staticmethod
    def _candidate_pairs(
        candidates: Sequence[ReferenceCandidate],
    ) -> tuple[tuple[str, str], ...]:
        return tuple((item.value, item.label) for item in candidates)

    @classmethod
    def _reference_fields(
        cls,
        fields: Iterable[FieldDefinition],
        prefix: tuple[str, ...] = (),
    ) -> Iterable[tuple[tuple[str, ...], FieldDefinition]]:
        for field_def in fields:
            path = (*prefix, field_def.key)
            if field_def.reference is not None:
                yield path, field_def
            if field_def.field_type == FieldType.BLOCK:
                yield from cls._reference_fields(field_def.block_fields, path)

    @staticmethod
    def _get_path(values: Mapping[str, Any], path: Sequence[str]) -> Any:
        current: Any = values
        for key in path:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _set_path(values: Dict[str, Any], path: Sequence[str], value: Any) -> None:
        current = values
        for key in path[:-1]:
            nested = current.get(key)
            if not isinstance(nested, dict):
                return
            current = nested
        current[path[-1]] = value

    @staticmethod
    def _cap_confidence(meta: Dict[str, Any], key: str, maximum: str) -> None:
        rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
        current = meta["confidence"].get(key, "unknown")
        if rank.get(current, 0) > rank[maximum]:
            meta["confidence"][key] = maximum

    @staticmethod
    def _append_reason(meta: Dict[str, Any], key: str, message: str) -> None:
        current = meta["reasons"].get(key)
        combined = f"{current} {message}" if current else message
        meta["reasons"][key] = combined[:1000]

    @classmethod
    def _mark_unresolved(
        cls,
        meta: Dict[str, Any],
        key: str,
        label: str,
        query: Any,
        match: _Match,
    ) -> None:
        meta["confidence"][key] = "unknown"
        suffix = " Найдено несколько равнозначных вариантов." if match.ambiguous else ""
        cls._append_reason(
            meta,
            key,
            f"Значение {query!r} для поля «{label}» не удалось однозначно "
            f"сопоставить с локальным справочником.{suffix}",
        )

    @staticmethod
    def _unresolved_warning(label: str, query: Any, match: _Match) -> str:
        alternatives = ", ".join(candidate.label for candidate in match.candidates[:3])
        suffix = f" Кандидаты: {alternatives}." if alternatives else ""
        return f"{label}: значение {query!r} не сопоставлено.{suffix}"[:1000]

    @staticmethod
    def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
