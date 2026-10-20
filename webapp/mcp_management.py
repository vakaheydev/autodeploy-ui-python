"""Operator-owned MCP tool policies and bounded, read-only catalog discovery."""
from __future__ import annotations

import fnmatch
import json
import re
import threading
import time
from pathlib import Path

from config.environments import OPENCODE_ALLOWED_MCP_KEY, OPENCODE_REPOSITORY_MCP_KEY, OPENCODE_REPOSITORY_GIT_PULL_KEY
from config.mcp_profiles import (
    AUTODEPLOY_MCP_NAME, choose_repository_mcp, repository_tool_allowlist, repository_tool_asklist, setting_enabled,
)
from opencode_integration.client import build_session_permissions
from opencode_integration.mcp_discovery import discover_mcp_tools

_NAME = re.compile(r"[A-Za-z0-9_.-]{1,200}")


class MCPManagement:
    def __init__(self, container):
        self.container = container
        self.path = Path(container.settings.data_dir) / "mcp-tool-policies.json"
        self._lock = threading.RLock()
        self._catalogs = {}

    def _load(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Некорректный файл политик MCP")
        for name, tools in data.items():
            if not _NAME.fullmatch(name) or not isinstance(tools, dict):
                raise ValueError("Некорректная политика MCP")
            if any(not _NAME.fullmatch(tool) or mode not in {"deny", "ask", "allow"} for tool, mode in tools.items()):
                raise ValueError("Некорректная политика инструмента MCP")
        return data

    def session_configuration(self):
        values = self.container.env_manager.load()
        names = list(dict.fromkeys(x.strip() for x in values.get(OPENCODE_ALLOWED_MCP_KEY, "").split(",") if x.strip()))
        if self.container.settings.mcp_enabled and AUTODEPLOY_MCP_NAME not in names:
            names.append(AUTODEPLOY_MCP_NAME)
        with self._lock:
            saved = self._load()
        return {
            "names": names, "repository": values.get(OPENCODE_REPOSITORY_MCP_KEY, ""),
            "allow_git_pull": setting_enabled(values.get(OPENCODE_REPOSITORY_GIT_PULL_KEY), default=True),
            "rules": [{"permission": f"{name}_{tool}", "pattern": "*", "action": mode}
                      for name in names for tool, mode in saved.get(name, {}).items()],
        }

    def catalog(self, name, *, refresh=False):
        if not _NAME.fullmatch(name):
            raise ValueError("Некорректное имя MCP")
        client = self.container.opencode_manager.client
        if client is None:
            raise RuntimeError("OpenCode не подключён")
        if name == AUTODEPLOY_MCP_NAME and self.container.settings.mcp_enabled:
            from webapp.mcp_server import available_tools
            rows = [{"name": tool["name"], "description": tool.get("description", ""),
                     "input_schema": tool.get("inputSchema", {})}
                    for tool in available_tools(self.container) if tool["name"] != "search_forms"]
        else:
            with self._lock:
                cached = self._catalogs.get(name)
                if cached and not refresh and time.monotonic() - cached[0] < 120:
                    rows = cached[1]
                else:
                    config = client.mcp_configurations().get(name)
                    if config is None:
                        raise ValueError("MCP не найден в конфигурации OpenCode")
                    try:
                        rows = discover_mcp_tools(config, client.directory)
                    except Exception:
                        # Exception strings may include headers/command env; never expose them.
                        raise RuntimeError("Не удалось получить tools/list MCP. Проверьте подключение и авторизацию сервера.") from None
                    self._catalogs[name] = (time.monotonic(), rows)
        with self._lock:
            overrides = self._load().get(name, {})
        configuration = self.session_configuration()
        repository = choose_repository_mcp(configuration["repository"], configuration["names"], client.list_mcp_servers())
        allow = repository_tool_allowlist(repository)
        ask = repository_tool_asklist(repository, allow_git_pull=setting_enabled(
            self.container.env_manager.load().get(OPENCODE_REPOSITORY_GIT_PULL_KEY), default=True,
        ))
        if name == AUTODEPLOY_MCP_NAME:
            from config.mcp_profiles import AUTODEPLOY_COPILOT_TOOLS
            extra_allow, extra_ask = self.container.plugin_ai_policy.copilot_tools()
            allow[name] = (*AUTODEPLOY_COPILOT_TOOLS, *extra_allow)
            ask[name] = extra_ask
        rules = build_session_permissions([name], allow, ask)
        items = []
        for row in rows:
            action = "deny"
            for rule in rules:
                if fnmatch.fnmatchcase(f"{name}_{row['name']}", rule["permission"]):
                    action = rule["action"]
            items.append({**row, "policy": overrides.get(row["name"], action)})
        return {"name": name, "tools": items, "enabled": name in configuration["names"]}

    def update(self, name, tool, policy):
        if not _NAME.fullmatch(tool) or policy not in {"deny", "ask", "allow"}:
            raise ValueError("Некорректное правило MCP")
        if tool not in {item["name"] for item in self.catalog(name)["tools"]}:
            raise ValueError("Инструмент отсутствует в каталоге MCP")
        applied = True
        if policy == "ask":
            applied = self.container.opencode_manager.client.clear_saved_mcp_permissions(name, tool)
        with self._lock:
            data = self._load()
            data.setdefault(name, {})[tool] = policy
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        return {"saved": True, "applies": "next_turn" if applied else "new_session"}

    def restart(self, name):
        client = self.container.opencode_manager.client
        if client is None:
            raise RuntimeError("OpenCode не подключён")
        if name not in client.list_mcp_servers():
            raise ValueError("Неизвестный MCP")
        client.restart_mcp(name)
        with self._lock:
            self._catalogs.pop(name, None)
        return {"restarted": True}
