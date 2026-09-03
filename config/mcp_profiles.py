"""Безопасные профили MCP-инструментов, известные приложению.

OpenCode загружает MCP-серверы из своей глобальной конфигурации. Приложение не
доверяет всему серверу целиком: для JSON Repository MCP разрешён только
проверенный список read-only tools из vakaheydev/local-json-repo-mcp.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable


JSON_REPOSITORY_READ_TOOLS: tuple[str, ...] = (
    "search_api_by_id",
    "search_api_by_name",
    "search_api_by_path",
    "search_api_by_backend_url",
    "search_api_by_policy",
    "search_api_by_tag",
    "search_api_by_host",
    "search_api_by_plan_name",
    "search_api_by_plan_id",
    "search_application_by_id",
    "search_application_by_name",
    "search_application_by_client_id",
    "search_application_by_api_id",
    "search_application_by_subscription_id",
    "search_repository",
    "list_apis",
    "list_applications",
    "get_api_definition",
    "get_application_definition",
    "get_json_definition",
    "get_json_fields",
    "get_json_value_by_path",
)

# Эти tools присутствуют в upstream MCP, но намеренно не выдаются агентам.
JSON_REPOSITORY_DENIED_TOOLS: tuple[str, ...] = (
    "diagnose_search",   # возвращает абсолютные локальные пути
)
JSON_REPOSITORY_CONFIRM_TOOLS: tuple[str, ...] = (
    "git_pull",          # обновляет managed worktree; всегда требует подтверждения
)


def repository_tool_allowlist(server_name: str) -> dict[str, tuple[str, ...]]:
    """Возвращает точный auto-allowlist для проверенного read-only MCP."""
    clean = str(server_name).strip()
    return {clean: JSON_REPOSITORY_READ_TOOLS} if clean else {}


def repository_tool_asklist(
    server_name: str,
    *,
    allow_git_pull: bool,
) -> dict[str, tuple[str, ...]]:
    """Особые инструменты, которые нельзя запускать без подтверждения."""
    clean = str(server_name).strip()
    if not clean or not allow_git_pull:
        return {}
    return {clean: JSON_REPOSITORY_CONFIRM_TOOLS}


def setting_enabled(value: Any, *, default: bool = True) -> bool:
    """Разбирает boolean из .env без неявного truthiness строк."""
    text = str(value).strip().casefold()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "да", "вкл"}:
        return True
    if text in {"0", "false", "no", "off", "нет", "выкл"}:
        return False
    return default


def choose_repository_mcp(
    configured: str,
    allowed: Iterable[str],
    statuses: Mapping[str, Mapping[str, Any]],
) -> str:
    """Fail-closed выбор JSON Repository MCP с удобным автоопределением.

    Явная настройка имеет приоритет. Без неё сервер выбирается автоматически
    только когда среди разрешённых и подключённых MCP кандидат ровно один.
    """
    allowed_names = list(dict.fromkeys(
        str(item).strip() for item in allowed if str(item).strip()
    ))
    selected = str(configured).strip()
    if selected:
        status = statuses.get(selected, {})
        return (
            selected
            if selected in allowed_names and status.get("status") == "connected"
            else ""
        )

    connected = [
        name
        for name in allowed_names
        if name and statuses.get(name, {}).get("status") == "connected"
    ]
    likely = [
        name for name in connected
        if any(token in name.casefold() for token in ("gravitee", "json", "repo"))
    ]
    if len(likely) == 1:
        return likely[0]
    return connected[0] if len(connected) == 1 else ""
