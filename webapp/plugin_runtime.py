"""Server-side runtime for custom pages registered by private packages."""
from __future__ import annotations

import copy
import dataclasses
import json
import math
import re
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Optional, Sequence

from forms.base_form import FormValidationIssue
from forms.fields import FieldDefinition, FieldType
from plugins.contracts import (
    PluginActionResult,
    PluginContext,
    PluginDefinition,
    PluginOperation,
    PluginView,
)
from plugins.registry import PluginRegistry
from webapp.form_runtime import (
    FormNotFoundError,
    FormVersionConflict,
    RuntimeValidation,
    _field_shape,
    _json_safe,
    _public_item,
    _visible,
)


_WIDGET_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,99}$")
_TONES = frozenset({"default", "info", "success", "warning", "danger"})
_CHART_TYPES = frozenset({"line", "area", "bar", "pie", "doughnut"})
_CHART_COLOR = re.compile(r"^(?:#[0-9a-fA-F]{3,8}|[a-zA-Z]{1,20})$")
_IMAGE_DATA = re.compile(
    # Raster formats only. Inline SVG is intentionally excluded because it can
    # carry active content and plugin output crosses a corporate trust boundary.
    r"^data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\r\n]+$"
)


def plugin_version(plugin: PluginDefinition) -> str:
    import hashlib

    shape = {
        "id": plugin.plugin_id,
        "title": plugin.title,
        "description": plugin.description,
        "category": plugin.category,
        "fields": [_field_shape(field) for field in plugin.fields],
        "operations": [{
            "id": item.operation_id,
            "label": item.label,
            "description": item.description,
            "ai_description": item.ai_description,
            "style": item.style,
            "confirmation": bool(item.confirmation_text),
            "require_valid_fields": item.require_valid_fields,
            "read_only": item.read_only,
            "idempotent": item.idempotent,
            "open_world": item.open_world,
        } for item in plugin.operations],
    }
    encoded = json.dumps(
        shape, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


class PluginRuntime:
    def __init__(self, container: Any, registry: PluginRegistry) -> None:
        self.container = container
        self.registry = registry

    def get(self, plugin_id: str) -> PluginDefinition:
        try:
            return self.registry.get(plugin_id)
        except KeyError as exc:
            raise FormNotFoundError(plugin_id) from exc

    def context(self, environment: str) -> PluginContext:
        self.container.forms._ensure_environment(environment)
        client = self.container.new_http_client()
        return PluginContext(
            environment=environment,
            env_manager=self.container.env_manager,
            http_client=client,
            reference_resolver=self.container.new_reference_resolver(),
            services=self.container.service_provider(self.container.env_manager, client),
        )

    def list_plugins(self) -> list[dict[str, Any]]:
        return [{
            "id": plugin.plugin_id,
            "title": plugin.title,
            "description": plugin.description,
            "category": plugin.category,
            "icon": plugin.icon,
            "keywords": list(dict.fromkeys(
                value for value in (
                    plugin.plugin_id,
                    plugin.title,
                    plugin.description,
                    plugin.category,
                    *plugin.keywords,
                ) if str(value).strip()
            )),
            "operation_count": len(plugin.operations),
        } for plugin in sorted(
            self.registry.all_plugins(),
            key=lambda item: (item.category.casefold(), item.title.casefold()),
        )]

    def describe(
        self,
        plugin_id: str,
        environment: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        plugin = self.get(plugin_id)
        context = self.context(environment)
        current = self.container.forms._with_defaults(
            plugin.fields, dict(values or {})
        )
        return {
            "id": plugin.plugin_id,
            "title": plugin.title,
            "description": plugin.description,
            "category": plugin.category,
            "icon": plugin.icon,
            "version": plugin_version(plugin),
            "fields": self._field_documents(plugin, environment, current),
            "initial_values": current,
            "operations": [self._operation_document(item) for item in plugin.operations],
            "widgets": self._render(plugin, context, current),
        }

    def state(
        self,
        plugin_id: str,
        environment: str,
        values: Mapping[str, Any],
        version: str = "",
    ) -> dict[str, Any]:
        plugin = self.get(plugin_id)
        self._check_version(plugin, version)
        return self.describe(plugin_id, environment, values)

    def validate(
        self,
        plugin_id: str,
        environment: str,
        values: Mapping[str, Any],
        version: str = "",
        *,
        validate_references: bool = True,
    ) -> RuntimeValidation:
        plugin = self.get(plugin_id)
        self._check_version(plugin, version)
        context = self.context(environment)
        raw = self.container.forms._with_defaults(plugin.fields, dict(values))
        errors: list[dict[str, Any]] = []
        canonical = self.container.forms._normalize_object(
            plugin.fields, raw, errors, environment, prefix=""
        )
        visible = tuple(
            field.key for field in plugin.fields if _visible(field, canonical)
        )
        canonical = {
            key: value
            for key, value in canonical.items()
            if self.container.forms._top_level_visible(plugin.fields, key, canonical)
        }
        if validate_references:
            self.container.forms._validate_references(
                plugin.fields, canonical, environment, errors
            )
        if plugin.validate is not None:
            raw_issues = plugin.validate(context, copy.deepcopy(canonical))
            if isinstance(raw_issues, (str, FormValidationIssue, Mapping)):
                issues: Sequence[Any] = (raw_issues,)
            else:
                issues = tuple(raw_issues or ())
            existing = {item["message"] for item in errors}
            for issue in issues:
                field, code, message = self.container.forms._domain_validation_issue(
                    issue, plugin.fields, canonical
                )
                if message and message not in existing:
                    errors.append({"field": field, "code": code, "message": message})
                    existing.add(message)
        return RuntimeValidation(not errors, canonical, tuple(errors), visible)

    def options(
        self,
        plugin_id: str,
        field_path: str,
        environment: str,
        values: Mapping[str, Any],
        query: str,
        offset: int,
        limit: int,
        refresh: bool,
    ) -> dict[str, Any]:
        plugin = self.get(plugin_id)
        self.container.forms._ensure_environment(environment)
        field, siblings = self.container.forms._find_field_context(
            plugin.fields, field_path
        )
        if field.reference is None:
            raise ValueError("Поле не связано со справочником")
        if refresh:
            self.container.reference_cache.invalidate(
                field.reference.resource, environment
            )
        scoped = self.container.forms._values_for_field_path(values, field_path)
        all_items = self.container.forms._resolve_reference(
            field, environment, scoped, siblings=siblings
        )
        keys = field.reference.search_keys or (field.reference.label_key,)
        needle = str(query).strip().casefold()
        filtered = [
            item for item in all_items
            if not needle or any(
                needle in str(item.get(key, "")).casefold() for key in keys
            )
        ]
        selected_values: list[Any] = []
        for key, value in scoped.items():
            if key == field.key or (
                key.startswith(f"{field.key}_")
                and key[len(field.key) + 1:].isdigit()
            ):
                selected_values.extend(value if isinstance(value, list) else [value])
        selected_ids = {
            str(value) for value in selected_values
            if not self.container.forms._empty(value)
        }
        if selected_ids:
            pinned = [
                item for item in all_items
                if str(item.get(field.reference.value_key, "")) in selected_ids
            ]
            filtered = pinned + [
                item for item in filtered
                if str(item.get(field.reference.value_key, "")) not in selected_ids
            ]
        total = len(filtered)
        page = filtered[offset:offset + limit]
        return {
            "items": [_public_item(item, field.reference) for item in page],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
        }

    def run_operation(
        self,
        plugin_id: str,
        operation_id: str,
        environment: str,
        values: Mapping[str, Any],
        version: str,
        confirmation_token: str = "",
        *,
        invoked_by_ai: bool = False,
    ) -> dict[str, Any]:
        plugin = self.get(plugin_id)
        self._check_version(plugin, version)
        operation = next(
            (item for item in plugin.operations if item.operation_id == operation_id),
            None,
        )
        if operation is None:
            raise FormNotFoundError(operation_id)
        validation = self.validate(
            plugin_id,
            environment,
            values,
            version,
            validate_references=operation.require_valid_fields,
        )
        if operation.require_valid_fields and not validation.valid:
            return {
                "success": False,
                "validation": dataclasses.asdict(validation),
                "message": "Поля страницы не прошли валидацию",
            }
        fingerprint = self.container.fingerprint(
            f"plugin:{plugin_id}:{operation_id}",
            environment,
            validation.values,
            plugin_version(plugin),
        )
        if (
            operation.confirmation_text
            and not invoked_by_ai
            and not self.container.confirmations.consume(
                confirmation_token, fingerprint
            )
        ):
            return {
                "success": False,
                "confirmation_required": True,
                "confirmation_text": operation.confirmation_text,
                "confirmation_token": self.container.confirmations.issue(fingerprint),
            }
        context = self.context(environment)
        raw_result = operation.handler(
            context, copy.deepcopy(validation.values)
        )
        result = self._action_result(raw_result)
        combined = copy.deepcopy(validation.values)
        combined.update(copy.deepcopy(dict(result.values)))
        normalized = self.validate(
            plugin_id,
            environment,
            combined,
            version,
            validate_references=False,
        )
        widgets = (
            self._serialize_widgets(result.widgets)
            if result.widgets is not None
            else self._render(plugin, context, normalized.values)
        )
        if result.data is not None and not widgets:
            widgets = [{
                "id": "operation-result",
                "kind": "text",
                "title": "Результат",
                "text": json.dumps(_json_safe(result.data), ensure_ascii=False, indent=2),
                "tone": "default",
            }]
        return {
            "success": True,
            "message": str(result.message or "Действие выполнено"),
            "values": _json_safe(normalized.values),
            "fields": self._field_documents(
                plugin, environment, normalized.values
            ),
            "widgets": widgets,
            "data": _json_safe(result.data),
            "validation": dataclasses.asdict(normalized),
        }

    def _field_documents(
        self,
        plugin: PluginDefinition,
        environment: str,
        values: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        owner = SimpleNamespace(form_id=plugin.plugin_id)
        return [
            self.container.forms._field_document(
                owner,
                field,
                environment,
                values,
                siblings=plugin.fields,
                reference_namespace="plugins",
            )
            for field in plugin.fields
        ]

    @staticmethod
    def _operation_document(operation: PluginOperation) -> dict[str, Any]:
        return {
            "id": operation.operation_id,
            "label": operation.label,
            "description": operation.description,
            "style": str(operation.style).strip().casefold(),
            "confirmation_required": bool(operation.confirmation_text),
            "requires_valid_fields": operation.require_valid_fields,
        }

    @staticmethod
    def _action_result(value: Any) -> PluginActionResult:
        if value is None:
            return PluginActionResult()
        if isinstance(value, PluginActionResult):
            return value
        if isinstance(value, Mapping):
            known = {"message", "values", "widgets", "data"}
            unexpected = set(value) - known
            if unexpected:
                raise ValueError(
                    "Plugin action вернул неизвестные поля: "
                    + ", ".join(sorted(str(item) for item in unexpected))
                )
            values = value.get("values") or {}
            if not isinstance(values, Mapping):
                raise TypeError("Plugin action values должен быть объектом")
            widgets = value.get("widgets")
            if widgets is not None and not isinstance(widgets, (list, tuple)):
                raise TypeError("Plugin action widgets должен быть массивом")
            return PluginActionResult(
                message=str(value.get("message") or "Действие выполнено"),
                values=values,
                widgets=widgets,
                data=value.get("data"),
            )
        return PluginActionResult(data=value)

    def _render(
        self,
        plugin: PluginDefinition,
        context: PluginContext,
        values: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if plugin.render is None:
            return []
        raw = plugin.render(context, copy.deepcopy(dict(values)))
        if raw is None:
            return []
        if isinstance(raw, PluginView):
            return self._serialize_widgets(raw.widgets)
        if isinstance(raw, (list, tuple)):
            return self._serialize_widgets(raw)
        raise TypeError("Plugin render должен вернуть PluginView, sequence или None")

    def _serialize_widgets(self, widgets: Iterable[Any]) -> list[dict[str, Any]]:
        result = [self._serialize_widget(widget) for widget in widgets]
        if len(result) > 100:
            raise ValueError("Страница плагина вернула больше 100 виджетов")
        identifiers = [item["id"] for item in result]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("widget_id на странице плагина должны быть уникальными")
        return result

    @staticmethod
    def _serialize_widget(widget: Any) -> dict[str, Any]:
        if dataclasses.is_dataclass(widget) and not isinstance(widget, type):
            raw = dataclasses.asdict(widget)
        elif isinstance(widget, Mapping):
            raw = dict(widget)
        else:
            raise TypeError("Виджет плагина должен быть dataclass или mapping")
        kind = str(raw.get("kind") or "")
        identifier = str(raw.pop("widget_id", raw.get("id", "")) or "")
        raw["id"] = identifier
        raw["kind"] = kind
        if not _WIDGET_ID.fullmatch(identifier):
            raise ValueError(f"Некорректный widget_id {identifier!r}")
        if kind not in {"text", "metric", "image", "chart", "table"}:
            raise ValueError(f"Неизвестный тип виджета {kind!r}")
        if kind == "text":
            raw["text"] = str(raw.get("text") or "")[:100_000]
            raw["tone"] = PluginRuntime._tone(raw.get("tone"))
        elif kind == "metric":
            raw["label"] = str(raw.get("label") or "")[:500]
            raw["value"] = _json_safe(raw.get("value"))
            raw["detail"] = str(raw.get("detail") or "")[:2000]
            raw["tone"] = PluginRuntime._tone(raw.get("tone"))
        elif kind == "image":
            src = str(raw.get("src") or "")
            if not (src.startswith("/") or (_IMAGE_DATA.fullmatch(src) and len(src) <= 3_000_000)):
                raise ValueError(
                    "ImageWidget.src должен быть same-origin путём или безопасным data:image URL"
                )
            raw["src"] = src
            raw["alt"] = str(raw.get("alt") or "")[:1000]
        elif kind == "chart":
            chart_type = str(raw.get("chart_type") or "line")
            if chart_type not in _CHART_TYPES:
                raise ValueError("chart_type должен быть line, area, bar, pie или doughnut")
            labels = [str(item)[:500] for item in raw.get("labels") or []]
            if len(labels) > 500:
                raise ValueError("График содержит больше 500 точек")
            series = []
            for item in raw.get("series") or []:
                value = dataclasses.asdict(item) if dataclasses.is_dataclass(item) else dict(item)
                points = [float(number) for number in value.get("values") or []]
                if len(points) != len(labels) or not all(math.isfinite(number) for number in points):
                    raise ValueError("Каждая серия графика должна содержать конечное число для каждой метки")
                color = str(value.get("color") or "")[:40]
                if color and not _CHART_COLOR.fullmatch(color):
                    raise ValueError("Цвет серии графика должен быть CSS-именем или hex-кодом")
                series.append({
                    "name": str(value.get("name") or "")[:500],
                    "values": points,
                    "color": color,
                })
            if not series:
                raise ValueError("График должен содержать хотя бы одну серию")
            if chart_type in {"pie", "doughnut"} and len(series) != 1:
                raise ValueError("Круговая диаграмма должна содержать ровно одну серию")
            raw.update({"chart_type": chart_type, "labels": labels, "series": series})
        elif kind == "table":
            columns = [str(item)[:500] for item in raw.get("columns") or []]
            rows = [list(row) for row in raw.get("rows") or []]
            if not columns or len(columns) > 50 or len(rows) > 1000:
                raise ValueError("Таблица должна содержать 1..50 колонок и не более 1000 строк")
            if any(len(row) != len(columns) for row in rows):
                raise ValueError("Число значений строки таблицы не совпадает с колонками")
            raw.update({"columns": columns, "rows": _json_safe(rows)})
        for key in ("title", "caption", "y_label"):
            if key in raw:
                raw[key] = str(raw.get(key) or "")[:2000]
        return _json_safe(raw)

    @staticmethod
    def _tone(value: Any) -> str:
        tone = str(value or "default")
        return tone if tone in _TONES else "default"

    @staticmethod
    def _check_version(plugin: PluginDefinition, requested: str) -> None:
        current = plugin_version(plugin)
        if requested and requested != current:
            raise FormVersionConflict(
                "Описание плагина изменилось. Обновите страницу перед продолжением."
            )
