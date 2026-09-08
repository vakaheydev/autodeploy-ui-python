"""Streamable HTTP MCP façade over the public AutoDeploy API core.

The tools deliberately stop before submission.  An agent can discover a form,
resolve references, validate values and prepare a preview, while the browser
still owns the explicit human confirmation and submit step.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import Any, Callable, Mapping, Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from config.categories import CATEGORIES
from config.environments import ENVIRONMENTS
from config.mcp_profiles import AUTODEPLOY_MCP_NAME, AUTODEPLOY_MCP_TOOLS
from opencode_integration.context_builder import redact_text
from webapp import __version__
from webapp.plugin_policy import PLUGIN_DISCOVERY_TOOLS, plugin_operation_tool_name


MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_SERVER_NAME = AUTODEPLOY_MCP_NAME
MCP_TOOL_NAMES = AUTODEPLOY_MCP_TOOLS

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required),
    }


_ENV = {"type": "string", "description": "Environment key returned by list_environments."}
_FORM = {"type": "string", "minLength": 1, "description": "Stable form id returned by search_forms."}
_VALUES = {"type": "object", "description": "Current form values keyed exactly as in get_form_schema."}
_WORKFLOW = {
    "type": "string",
    "minLength": 20,
    "maxLength": 200,
    "description": "Opaque workflow id supplied in the trusted Copilot session context.",
}
_JSON_VALUE = {
    "description": "JSON value matching the selected field type. For a repeated BLOCK base path, prefer an array whose items are complete block objects.",
    "anyOf": [
        {"type": "string", "maxLength": 100000},
        {"type": "number"},
        {"type": "boolean"},
        {"type": "null"},
        {"type": "array", "maxItems": 1000},
        {"type": "object", "maxProperties": 500},
    ],
}

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_system_status",
        "description": "Check the AutoDeploy server, form catalog and OpenCode connection before a workflow.",
        "inputSchema": _object_schema({}),
    },
    {
        "name": "list_environments",
        "description": "List valid environment keys. Use the returned key in every environment argument; never invent one.",
        "inputSchema": _object_schema({}),
    },
    {
        "name": "search_forms",
        "description": "Deterministic keyword search over the Python form catalog. External MCP clients may use it directly; Gravitee Copilot should prefer semantic_search_forms when it has a workflow id.",
        "inputSchema": _object_schema({
            "query": {"type": "string", "default": "", "maxLength": 500},
            "category": {"type": "string", "default": "", "maxLength": 80},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        }),
    },
    {
        "name": "semantic_search_forms",
        "description": "Ask the workflow's long-lived, none-thinking semantic search session for relevant forms. Use when a user request may require a form and no exact form id is already established. The returned entries are authoritative catalog descriptions enriched with semantic score/reason. Do not call for greetings or ordinary conversation.",
        "inputSchema": _object_schema({
            "workflow_id": _WORKFLOW,
            "query": {"type": "string", "minLength": 1, "maxLength": 10000},
            "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        }, ("workflow_id", "query")),
    },
    {
        "name": "get_form_schema",
        "description": "Return the live server-computed form document: field types, required flags, dependencies, references, inline options and version. Always call after choosing a form and before proposing values. Select and multiselect are distinct types.",
        "inputSchema": _object_schema({"form_id": _FORM, "environment": _ENV}, ("form_id", "environment")),
    },
    {
        "name": "calculate_form_state",
        "description": "Recalculate dynamic visibility, defaults and dependent fields for current values. Use after changing a value that controls other fields.",
        "inputSchema": _object_schema({"form_id": _FORM, "environment": _ENV, "values": _VALUES, "form_version": {"type": "string"}}, ("form_id", "environment", "values", "form_version")),
    },
    {
        "name": "search_reference_options",
        "description": "Search valid values for one select or multiselect field. Use its field path from get_form_schema. The returned value is the only identifier that may be written to the form; labels are presentation only.",
        "inputSchema": _object_schema({
            "form_id": _FORM, "environment": _ENV,
            "field_path": {"type": "string", "minLength": 1},
            "values": _VALUES,
            "query": {"type": "string", "default": "", "maxLength": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
        }, ("form_id", "environment", "field_path", "values")),
    },
    {
        "name": "validate_form_values",
        "description": "Run authoritative Python schema, reference and domain validation. Call before claiming a form is ready. This tool does not submit anything.",
        "inputSchema": _object_schema({"form_id": _FORM, "environment": _ENV, "values": _VALUES, "form_version": {"type": "string"}}, ("form_id", "environment", "values", "form_version")),
    },
    {
        "name": "preview_form_submission",
        "description": "Build the exact server-side request preview after validation. It never sends the request. The human must review and submit in the web UI.",
        "inputSchema": _object_schema({"form_id": _FORM, "environment": _ENV, "values": _VALUES, "form_version": {"type": "string"}}, ("form_id", "environment", "values", "form_version")),
    },
    {
        "name": "prepare_form_draft",
        "description": "Create or revise a persistent local form draft after get_form_schema. Pass only evidenced field proposals and the live form version. For a repeated BLOCK, prefer one proposal at its base path with an array of objects; Python expands it to every instance. Canonical individual paths use the base name for the first instance and _2, _3 for later instances (for example plan.name, plan_2.name, plan_3.name). Zero-based plan[0].name and plan.0.name are also normalized. Python resolves references, recalculates state and validates. The draft remains available until successful submission or explicit deletion. This never submits or calls an external write. Use draft_id only when revising an existing draft.",
        "inputSchema": _object_schema({
            "workflow_id": _WORKFLOW,
            "form_id": _FORM,
            "environment": _ENV,
            "form_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "draft_id": {"type": "string", "default": "", "maxLength": 200},
            "proposals": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": _object_schema({
                    "field_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "Path from get_form_schema. For repeated blocks, prefer the base block path with an array value; canonical later instances use _2, _3 suffixes.",
                    },
                    "value": _JSON_VALUE,
                    "confidence": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
                    "source": {"type": "string", "minLength": 1, "maxLength": 500},
                    "reason": {"type": "string", "default": "", "maxLength": 1000},
                    "conflict": {"type": "string", "default": "", "maxLength": 1000},
                }, ("field_path", "value", "confidence", "source")),
            },
        }, ("workflow_id", "form_id", "environment", "form_version", "proposals")),
    },
    {
        "name": "research_repository",
        "description": "Delegate a genuinely complex multi-file JSON Repository investigation to a separate short-lived read-only Researcher session. Use only for a concrete missing fact that cannot be answered by a simple targeted lookup. Never use for form discovery, form dictionaries, SELECT/MULTISELECT resolution or facts already provided by the operator.",
        "inputSchema": _object_schema({
            "workflow_id": _WORKFLOW,
            "question": {"type": "string", "minLength": 1, "maxLength": 20000},
            "environment": _ENV,
            "required_facts": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                "maxItems": 30,
                "default": [],
            },
            "depth": {"type": "string", "enum": ["focused", "deep"], "default": "focused"},
        }, ("workflow_id", "question", "environment")),
    },
    {
        "name": "search_gravitee_objects",
        "description": "Search APIs or applications through the configured read-only corporate reference service. Use only for repository facts, not for small form dictionaries already returned by get_form_schema.",
        "inputSchema": _object_schema({
            "kind": {"type": "string", "enum": ["api", "application"]},
            "environments": {"type": "array", "items": _ENV, "minItems": 1, "maxItems": 6, "uniqueItems": True},
            "query": {"type": "string", "minLength": 1, "maxLength": 500},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
        }, ("kind", "environments", "query")),
    },
)

for _tool in TOOLS:
    _tool["annotations"] = {
        "readOnlyHint": _tool["name"] != "prepare_form_draft",
        "destructiveHint": False,
        # Draft creation is content-addressed per workflow; provider retries
        # return the same draft instead of multiplying local state.
        "idempotentHint": True,
        "openWorldHint": _tool["name"] in {
            "search_gravitee_objects", "research_repository",
        },
    }


def _plugin_tools(container: Any) -> list[dict[str, Any]]:
    """Build the current fail-closed plugin tool catalog."""
    visible = container.plugin_ai_policy.visible_plugins()
    if not visible:
        return []
    plugin_ids = [item.plugin_id for item in visible]
    tools: list[dict[str, Any]] = [
        {
            "name": "list_plugins",
            "description": (
                "List corporate custom pages explicitly made visible to this AI. "
                "Use this only when the operator asks about a plugin page or a "
                "workflow exposed by one; ordinary form discovery still uses "
                "semantic_search_forms."
            ),
            "inputSchema": _object_schema({}),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "get_plugin_page",
            "description": (
                "Return the live fields, reference endpoints, dynamic widgets and "
                "AI-visible operations of one corporate plugin page. Always read "
                "this document before calling a plugin operation."
            ),
            "inputSchema": _object_schema({
                "plugin_id": {
                    "type": "string",
                    "enum": plugin_ids,
                    "description": "Stable id returned by list_plugins.",
                },
                "environment": _ENV,
            }, ("plugin_id", "environment")),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "calculate_plugin_state",
            "description": (
                "Recalculate visible and conditional fields plus dynamic widgets "
                "for current values of an AI-visible corporate plugin page. Use "
                "this after changing a value that can affect page state."
            ),
            "inputSchema": _object_schema({
                "plugin_id": {
                    "type": "string",
                    "enum": plugin_ids,
                    "description": "Stable id returned by list_plugins.",
                },
                "environment": _ENV,
                "values": {
                    "type": "object",
                    "description": "Current plugin values keyed exactly as in get_plugin_page.",
                },
                "plugin_version": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
            }, ("plugin_id", "environment", "values", "plugin_version")),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "search_plugin_reference_options",
            "description": (
                "Resolve a SELECT or MULTISELECT on an AI-visible plugin page. "
                "Use the exact field path and current values from the live page; "
                "return and pass value_key IDs, never guessed labels."
            ),
            "inputSchema": _object_schema({
                "plugin_id": {
                    "type": "string",
                    "enum": plugin_ids,
                    "description": "Stable id returned by list_plugins.",
                },
                "field_path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "environment": _ENV,
                "values": {
                    "type": "object",
                    "description": "Complete current plugin values, including dependencies.",
                },
                "query": {
                    "type": "string",
                    "maxLength": 1000,
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                },
            }, ("plugin_id", "field_path", "environment", "values")),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        },
        {
            "name": "validate_plugin_values",
            "description": (
                "Run authoritative Python structural, reference and corporate "
                "validation for current values of an AI-visible plugin page."
            ),
            "inputSchema": _object_schema({
                "plugin_id": {
                    "type": "string",
                    "enum": plugin_ids,
                    "description": "Stable id returned by list_plugins.",
                },
                "environment": _ENV,
                "values": {
                    "type": "object",
                    "description": "Complete current plugin values.",
                },
                "plugin_version": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
            }, ("plugin_id", "environment", "values", "plugin_version")),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        },
    ]
    for plugin in visible:
        for operation in plugin.operations:
            policy = container.plugin_ai_policy.operation_policy(
                plugin.plugin_id, operation.operation_id
            )
            if policy == "deny":
                continue
            tools.append({
                "name": plugin_operation_tool_name(
                    plugin.plugin_id, operation.operation_id
                ),
                "description": (
                    f"Plugin {plugin.title!r}, operation {operation.label!r}. "
                    + (operation.ai_description or operation.description)
                    + " Pass the complete current values and live plugin_version "
                    "from get_plugin_page. The Python plugin owns validation and execution."
                ).strip(),
                "inputSchema": _object_schema({
                    "environment": _ENV,
                    "values": {
                        "type": "object",
                        "description": "Current plugin page values keyed exactly as in get_plugin_page.",
                    },
                    "plugin_version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                }, ("environment", "values", "plugin_version")),
                "annotations": {
                    "readOnlyHint": bool(operation.read_only),
                    "destructiveHint": not bool(operation.read_only),
                    "idempotentHint": bool(operation.idempotent),
                    "openWorldHint": bool(operation.open_world),
                },
            })
    return tools


def available_tools(container: Any) -> list[dict[str, Any]]:
    return [*TOOLS, *_plugin_tools(container)]


def _enabled(request: Request) -> bool:
    # Process settings define whether the endpoint exists for this server run.
    return bool(request.app.state.container.settings.mcp_enabled)


def _jsonrpc(identifier: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    document: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier}
    document["error" if error is not None else "result"] = error if error is not None else result
    return document


def _require_arguments(arguments: Any) -> dict[str, Any]:
    if arguments is None:
        return {}
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    return arguments


class MCPTools:
    def __init__(self, container: Any) -> None:
        self.container = container

    def call(self, name: str, arguments: Any) -> Any:
        values = _require_arguments(arguments)
        if name in MCP_TOOL_NAMES:
            return getattr(self, name)(**values)
        if name in PLUGIN_DISCOVERY_TOOLS:
            return getattr(self, name)(**values)
        return self._call_plugin_operation(name, values)

    def list_plugins(self) -> dict[str, Any]:
        visible = {
            item.plugin_id for item in self.container.plugin_ai_policy.visible_plugins()
        }
        items = [
            item for item in self.container.plugins.list_plugins()
            if item["id"] in visible
        ]
        return {"items": items, "total": len(items)}

    def get_plugin_page(self, plugin_id: str, environment: str) -> dict[str, Any]:
        self._require_visible_plugin(plugin_id)
        document = self.container.plugins.describe(plugin_id, environment)
        plugin = self.container.plugins.get(plugin_id)
        allowed_operations = []
        for operation in plugin.operations:
            policy = self.container.plugin_ai_policy.operation_policy(
                plugin_id, operation.operation_id
            )
            if policy == "deny":
                continue
            allowed_operations.append({
                "id": operation.operation_id,
                "label": operation.label,
                "description": operation.ai_description or operation.description,
                "policy": policy,
                "tool_name": plugin_operation_tool_name(
                    plugin_id, operation.operation_id
                ),
            })
        document["operations"] = allowed_operations
        return document

    def calculate_plugin_state(
        self,
        plugin_id: str,
        environment: str,
        values: Mapping[str, Any],
        plugin_version: str,
    ) -> dict[str, Any]:
        self._require_visible_plugin(plugin_id)
        document = self.container.plugins.state(
            plugin_id, environment, values, plugin_version
        )
        # Do not leak operations that policy removed since session creation.
        allowed = {
            operation.operation_id
            for operation in self.container.plugins.get(plugin_id).operations
            if self.container.plugin_ai_policy.operation_policy(
                plugin_id, operation.operation_id
            ) != "deny"
        }
        document["operations"] = [
            operation for operation in document["operations"]
            if operation["id"] in allowed
        ]
        return document

    def search_plugin_reference_options(
        self,
        plugin_id: str,
        field_path: str,
        environment: str,
        values: Mapping[str, Any],
        query: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        self._require_visible_plugin(plugin_id)
        bounded_limit = int(limit)
        if not 1 <= bounded_limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return self.container.plugins.options(
            plugin_id,
            field_path,
            environment,
            values,
            str(query),
            0,
            bounded_limit,
            False,
        )

    def validate_plugin_values(
        self,
        plugin_id: str,
        environment: str,
        values: Mapping[str, Any],
        plugin_version: str,
    ) -> dict[str, Any]:
        self._require_visible_plugin(plugin_id)
        return dataclasses.asdict(self.container.plugins.validate(
            plugin_id, environment, values, plugin_version
        ))

    def _require_visible_plugin(self, plugin_id: str) -> None:
        visible = {
            item.plugin_id for item in self.container.plugin_ai_policy.visible_plugins()
        }
        if plugin_id not in visible:
            raise PermissionError("Плагин не разрешён для AI")

    def _call_plugin_operation(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> Any:
        for plugin in self.container.plugin_ai_policy.visible_plugins():
            for operation in plugin.operations:
                if plugin_operation_tool_name(
                    plugin.plugin_id, operation.operation_id
                ) != tool_name:
                    continue
                policy = self.container.plugin_ai_policy.operation_policy(
                    plugin.plugin_id, operation.operation_id
                )
                if policy == "deny":
                    raise PermissionError("Операция плагина запрещена для AI")
                return self.container.plugins.run_operation(
                    plugin.plugin_id,
                    operation.operation_id,
                    str(arguments.get("environment") or ""),
                    arguments.get("values") or {},
                    str(arguments.get("plugin_version") or ""),
                    invoked_by_ai=True,
                )
        raise KeyError(f"Unknown AutoDeploy tool: {tool_name}")

    def get_system_status(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "version": __version__,
            "forms": len(self.container.forms.list_forms()),
            "opencode": self.container.opencode_manager.status.state,
            "mcp": "enabled",
        }

    @staticmethod
    def list_environments() -> dict[str, Any]:
        return {"items": [dataclasses.asdict(item) for item in ENVIRONMENTS]}

    def search_forms(self, query: str = "", category: str = "", limit: int = 20) -> dict[str, Any]:
        if not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        forms = self.container.forms.list_forms(str(category).strip())
        words = [word.casefold() for word in str(query).split() if word]
        ranked: list[tuple[int, dict[str, Any]]] = []
        for form in forms:
            haystack = " ".join(form.get("keywords", ())).casefold()
            if words and not all(word in haystack for word in words):
                continue
            score = sum(8 if word in form["title"].casefold() else 3 for word in words)
            ranked.append((score, form))
        ranked.sort(key=lambda item: (-item[0], item[1]["title"]))
        return {"items": [item for _, item in ranked[: int(limit)]], "total": len(ranked)}

    def semantic_search_forms(
        self, workflow_id: str, query: str, limit: int = 5
    ) -> dict[str, Any]:
        return self.container.ai.semantic_search_forms(
            workflow_id, query=str(query), limit=int(limit)
        )

    def get_form_schema(self, form_id: str, environment: str) -> Any:
        return self.container.forms.describe(form_id, environment)

    def calculate_form_state(self, form_id: str, environment: str, values: Mapping[str, Any], form_version: str) -> Any:
        return self.container.forms.state(form_id, environment, values, form_version)

    def search_reference_options(self, form_id: str, environment: str, field_path: str, values: Mapping[str, Any], query: str = "", offset: int = 0, limit: int = 50) -> Any:
        return self.container.forms.options(form_id, field_path, environment, values, query, int(offset), int(limit), False)

    def validate_form_values(self, form_id: str, environment: str, values: Mapping[str, Any], form_version: str) -> Any:
        return dataclasses.asdict(self.container.forms.validate(form_id, environment, values, form_version))

    def preview_form_submission(self, form_id: str, environment: str, values: Mapping[str, Any], form_version: str) -> Any:
        return self.container.forms.preview(form_id, environment, values, form_version)

    def prepare_form_draft(
        self,
        workflow_id: str,
        form_id: str,
        environment: str,
        form_version: str,
        proposals: list[Mapping[str, Any]],
        draft_id: str = "",
    ) -> Any:
        return self.container.ai.prepare_form_draft(
            workflow_id,
            form_id=form_id,
            environment=environment,
            form_version=form_version,
            proposals=proposals,
            draft_id=draft_id,
        )

    def research_repository(
        self,
        workflow_id: str,
        question: str,
        environment: str,
        required_facts: Optional[list[str]] = None,
        depth: str = "focused",
    ) -> Any:
        return self.container.ai.research_repository(
            workflow_id,
            question=question,
            environment=environment,
            required_facts=required_facts or [],
            depth=depth,
        )

    def search_gravitee_objects(self, kind: str, environments: list[str], query: str, limit: int = 50) -> Any:
        return self.container.forms.search(kind, environments, query, int(limit), False)


def _handle_call(request: Request, message: Mapping[str, Any]) -> dict[str, Any] | None:
    identifier = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return _jsonrpc(identifier, error={"code": -32600, "message": "Invalid Request"})
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if method == "initialize":
        params = message.get("params")
        requested = str(params.get("protocolVersion", MCP_PROTOCOL_VERSION)) if isinstance(params, Mapping) else MCP_PROTOCOL_VERSION
        return _jsonrpc(identifier, {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "gravitee-autodeploy", "version": request.app.version},
            "instructions": "For an AI workflow, discover forms lazily with semantic_search_forms, read the chosen live schema, resolve select values through form options, then prepare_form_draft. Corporate custom pages are a separate concept: use list_plugins only when relevant, then get_plugin_page; use calculate_plugin_state, search_plugin_reference_options and validate_plugin_values as needed, and call only the operation-specific tool exposed by policy. A manual-policy tool is executed only after the operator approves it in OpenCode. Use research_repository only for a bounded complex JSON Repository question. Never claim a form submission: every draft requires human review and the web UI owns submit.",
        })
    if method == "ping":
        return _jsonrpc(identifier, {})
    if method == "tools/list":
        return _jsonrpc(identifier, {
            "tools": available_tools(request.app.state.container)
        })
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            if not isinstance(params, Mapping):
                raise ValueError("tool call params must be an object")
            result = MCPTools(request.app.state.container).call(
                str(params.get("name", "")), params.get("arguments", {})
            )
            text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
            return _jsonrpc(identifier, {
                "content": [{"type": "text", "text": text}],
                "structuredContent": result,
                "isError": False,
            })
        except Exception as exc:
            return _jsonrpc(identifier, {
                "content": [{"type": "text", "text": redact_text(str(exc))[:2000]}],
                "isError": True,
            })
    return _jsonrpc(identifier, error={"code": -32601, "message": "Method not found"})


@router.post("")
async def mcp(request: Request):
    if not _enabled(request):
        return JSONResponse(status_code=404, content={"error": {"code": "mcp_disabled", "message": "AutoDeploy MCP отключён"}})
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(_jsonrpc(None, error={"code": -32700, "message": "Parse error"}), status_code=400)
    messages = payload if isinstance(payload, list) else [payload]
    if not messages or not all(isinstance(item, dict) for item in messages):
        return JSONResponse(_jsonrpc(None, error={"code": -32600, "message": "Invalid Request"}), status_code=400)
    # Some tools intentionally orchestrate a separate OpenCode session. Keep
    # those blocking HTTP calls off FastAPI's event loop.
    replies = []
    for item in messages:
        reply = await asyncio.to_thread(_handle_call, request, item)
        if reply is not None:
            replies.append(reply)
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if isinstance(payload, list) else replies[0])


@router.delete("")
def close_mcp(request: Request):
    if not _enabled(request):
        return Response(status_code=404)
    return Response(status_code=204)
