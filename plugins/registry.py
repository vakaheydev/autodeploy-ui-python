"""Process-local registry for private plugin page declarations."""
from __future__ import annotations

import re
from typing import Dict, List

from forms.fields import FieldDefinition
from plugins.contracts import PluginDefinition, PluginOperation


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


class PluginRegistry:
    """Registry owned by the web composition root, not by React."""

    def __init__(self) -> None:
        self._plugins: Dict[str, PluginDefinition] = {}

    def register(self, plugin: PluginDefinition) -> None:
        if not isinstance(plugin, PluginDefinition):
            raise TypeError("Plugin registry принимает только PluginDefinition")
        if not _IDENTIFIER.fullmatch(plugin.plugin_id):
            raise ValueError(
                "plugin_id должен начинаться с маленькой латинской буквы и "
                "содержать только a-z, 0-9, точку, дефис или подчёркивание"
            )
        if not plugin.title.strip():
            raise ValueError("Название плагина не может быть пустым")
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"Плагин {plugin.plugin_id!r} уже зарегистрирован")
        if isinstance(plugin.keywords, str) or not all(
            isinstance(item, str) for item in plugin.keywords
        ):
            raise TypeError("keywords плагина должен быть sequence строк")
        if not all(isinstance(item, FieldDefinition) for item in plugin.fields):
            raise TypeError("fields плагина должны содержать FieldDefinition")
        field_keys = [field.key for field in plugin.fields]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError(f"Поля плагина {plugin.plugin_id!r} должны иметь уникальные key")
        if not all(isinstance(item, PluginOperation) for item in plugin.operations):
            raise TypeError("operations плагина должны содержать PluginOperation")
        operation_ids = [item.operation_id for item in plugin.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError(
                f"Операции плагина {plugin.plugin_id!r} должны иметь уникальные operation_id"
            )
        for operation in plugin.operations:
            if not _IDENTIFIER.fullmatch(operation.operation_id):
                raise ValueError(
                    f"Некорректный operation_id {operation.operation_id!r} в {plugin.plugin_id!r}"
                )
            if not operation.label.strip():
                raise ValueError("Название операции плагина не может быть пустым")
            if not callable(operation.handler):
                raise TypeError(
                    f"Handler операции {plugin.plugin_id}.{operation.operation_id} "
                    "должен быть callable"
                )
            if str(operation.style).strip().casefold() not in {
                "primary", "secondary", "success", "danger",
            }:
                raise ValueError(
                    f"Некорректный style операции {plugin.plugin_id}."
                    f"{operation.operation_id}: {operation.style!r}"
                )
        if plugin.render is not None and not callable(plugin.render):
            raise TypeError("PluginDefinition.render должен быть callable или None")
        if plugin.validate is not None and not callable(plugin.validate):
            raise TypeError("PluginDefinition.validate должен быть callable или None")
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> PluginDefinition:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise KeyError(f"Плагин {plugin_id!r} не зарегистрирован") from exc

    def all_plugins(self) -> List[PluginDefinition]:
        return list(self._plugins.values())

    def clear(self) -> None:
        self._plugins.clear()
