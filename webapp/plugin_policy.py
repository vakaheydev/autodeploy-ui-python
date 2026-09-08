"""Persistent, fail-closed AI policy for corporate page plugins."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any, Mapping

from plugins.registry import PluginRegistry


AI_POLICIES = frozenset({"deny", "allow", "manual"})
_TOOL_PART = re.compile(r"[^a-z0-9_]+")
PLUGIN_DISCOVERY_TOOLS = (
    "list_plugins",
    "get_plugin_page",
    "calculate_plugin_state",
    "search_plugin_reference_options",
    "validate_plugin_values",
)


def plugin_operation_tool_name(plugin_id: str, operation_id: str) -> str:
    """Return a stable MCP tool name (OpenAI-compatible and <= 64 chars)."""

    source = f"{plugin_id}:{operation_id}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    plugin = _TOOL_PART.sub("_", plugin_id.casefold()).strip("_")[:20] or "page"
    operation = _TOOL_PART.sub("_", operation_id.casefold()).strip("_")[:20] or "action"
    return f"plugin_{plugin}_{operation}_{digest}"[:64]


class PluginAIPolicyStore:
    """Stores only non-secret operator choices in the user data directory."""

    def __init__(self, path: Path, registry: PluginRegistry) -> None:
        self.path = Path(path)
        self.registry = registry
        self._lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        saved = self._load()
        saved_plugins = saved.get("plugins")
        configured = saved_plugins if isinstance(saved_plugins, Mapping) else {}
        plugins = []
        for plugin in sorted(self.registry.all_plugins(), key=lambda item: item.title.casefold()):
            raw = configured.get(plugin.plugin_id)
            policy = raw if isinstance(raw, Mapping) else {}
            raw_operations = policy.get("operations")
            operations = raw_operations if isinstance(raw_operations, Mapping) else {}
            plugins.append({
                "id": plugin.plugin_id,
                "title": plugin.title,
                "description": plugin.description,
                "visible": policy.get("visible") is True,
                "operations": [{
                    "id": operation.operation_id,
                    "label": operation.label,
                    "description": operation.ai_description or operation.description,
                    "policy": (
                        str(operations.get(operation.operation_id))
                        if str(operations.get(operation.operation_id)) in AI_POLICIES
                        else "deny"
                    ),
                    "tool_name": plugin_operation_tool_name(
                        plugin.plugin_id, operation.operation_id
                    ),
                } for operation in plugin.operations],
            })
        return {
            "ai_visible": saved.get("ai_visible") is True,
            "plugins": plugins,
            "requires_new_session": True,
        }

    def update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if set(payload) - {"ai_visible", "plugins"}:
            raise ValueError("AI policy содержит неизвестные поля")
        if not isinstance(payload.get("ai_visible"), bool):
            raise ValueError("ai_visible должен быть boolean")
        raw_plugins = payload.get("plugins")
        if not isinstance(raw_plugins, list):
            raise ValueError("plugins должен быть массивом")

        registered = {item.plugin_id: item for item in self.registry.all_plugins()}
        normalized: dict[str, Any] = {}
        for item in raw_plugins:
            if not isinstance(item, Mapping):
                raise ValueError("Элемент plugins должен быть объектом")
            if set(item) - {"id", "visible", "operations"}:
                raise ValueError("Настройка плагина содержит неизвестные поля")
            plugin_id = str(item.get("id") or "")
            plugin = registered.get(plugin_id)
            if plugin is None:
                raise ValueError(f"Неизвестный плагин {plugin_id!r}")
            if not isinstance(item.get("visible"), bool):
                raise ValueError(f"visible для {plugin_id!r} должен быть boolean")
            raw_operations = item.get("operations")
            if not isinstance(raw_operations, Mapping):
                raise ValueError(f"operations для {plugin_id!r} должен быть объектом")
            known = {operation.operation_id for operation in plugin.operations}
            unknown = sorted(set(str(key) for key in raw_operations) - known)
            if unknown:
                raise ValueError(
                    f"Неизвестные операции {plugin_id!r}: {', '.join(unknown)}"
                )
            operations: dict[str, str] = {}
            for operation_id in known:
                value = str(raw_operations.get(operation_id, "deny"))
                if value not in AI_POLICIES:
                    raise ValueError(
                        f"Политика {plugin_id}.{operation_id} должна быть "
                        "deny, allow или manual"
                    )
                operations[operation_id] = value
            normalized[plugin_id] = {
                "visible": bool(item["visible"]),
                "operations": operations,
            }

        document = {
            "version": 1,
            "ai_visible": bool(payload["ai_visible"]),
            "plugins": normalized,
        }
        self._save(document)
        return self.snapshot()

    def visible_plugins(self) -> list[Any]:
        snapshot = self.snapshot()
        if not snapshot["ai_visible"]:
            return []
        visible = {item["id"] for item in snapshot["plugins"] if item["visible"]}
        return [
            plugin for plugin in self.registry.all_plugins()
            if plugin.plugin_id in visible
        ]

    def operation_policy(self, plugin_id: str, operation_id: str) -> str:
        snapshot = self.snapshot()
        if not snapshot["ai_visible"]:
            return "deny"
        plugin = next(
            (item for item in snapshot["plugins"] if item["id"] == plugin_id),
            None,
        )
        if plugin is None or not plugin["visible"]:
            return "deny"
        operation = next(
            (item for item in plugin["operations"] if item["id"] == operation_id),
            None,
        )
        return str(operation["policy"]) if operation else "deny"

    def copilot_tools(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return exact auto-allow and manual-approval MCP tool lists."""

        allowed: list[str] = []
        manual: list[str] = []
        visible = self.visible_plugins()
        if visible:
            allowed.extend(PLUGIN_DISCOVERY_TOOLS)
        for plugin in visible:
            for operation in plugin.operations:
                name = plugin_operation_tool_name(
                    plugin.plugin_id, operation.operation_id
                )
                policy = self.operation_policy(
                    plugin.plugin_id, operation.operation_id
                )
                if policy == "allow":
                    allowed.append(name)
                elif policy == "manual":
                    manual.append(name)
        return tuple(allowed), tuple(manual)

    def _load(self) -> dict[str, Any]:
        with self._lock:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

    def _save(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
