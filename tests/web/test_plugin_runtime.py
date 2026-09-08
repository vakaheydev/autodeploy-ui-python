from __future__ import annotations

from pathlib import Path

import pytest

from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from plugins import (
    ChartSeries,
    ChartWidget,
    MetricWidget,
    PluginActionResult,
    PluginDefinition,
    PluginOperation,
    PluginRegistry,
    TextWidget,
)
from webapp.container import ApplicationContainer
from webapp.mcp_server import MCPTools, available_tools
from webapp.plugin_policy import plugin_operation_tool_name
from webapp.settings import WebSettings


def _settings(tmp_path: Path) -> WebSettings:
    return WebSettings(
        host="127.0.0.1",
        port=8765,
        project_root=Path(__file__).resolve().parents[2],
        data_dir=tmp_path / "data",
        env_file=tmp_path / ".env",
        static_dir=Path(__file__).resolve().parents[2] / "webapp" / "static",
        log_dir=tmp_path / "logs",
        max_request_bytes=2 * 1024 * 1024,
        auto_connect_opencode=False,
        open_browser=False,
        mcp_enabled=True,
    )


@pytest.fixture
def plugin_container(tmp_path: Path):
    container = ApplicationContainer(_settings(tmp_path))
    calls: list[dict[str, object]] = []

    def render(context, values):
        assert context.services.tfs is not None
        count = float(values.get("count") or 0)
        return [
            MetricWidget("total", "Количество", count),
            ChartWidget(
                "trend",
                labels=("Сейчас", "После"),
                series=(ChartSeries("Значение", (count, count + 1)),),
                chart_type="line",
            ),
        ]

    def execute(context, values):
        calls.append({
            "environment": context.environment,
            "count": values.get("count"),
            "service": context.services.tfs,
        })
        return PluginActionResult(
            message="Пересчитано",
            values={"count": float(values.get("count") or 0) + 1},
            widgets=(TextWidget("done", "Операция завершена", tone="success"),),
        )

    container.plugin_registry.register(PluginDefinition(
        plugin_id="reports.capacity",
        title="Capacity report",
        description="Корпоративный отчёт",
        category="Отчёты",
        keywords=("capacity", "нагрузка"),
        fields=(
            FieldDefinition("enabled", "Включить", FieldType.CHECKBOX, required=False),
            FieldDefinition("count", "Количество", FieldType.NUMBER, default=2),
            FieldDefinition(
                "category",
                "Категория",
                FieldType.SELECT,
                required=False,
                condition=lambda values: bool(values.get("enabled")),
                reference=ReferenceConfig(
                    source="local",
                    resource="api_categories.json",
                    value_key="id",
                    label_key="name",
                    search_keys=("name", "id"),
                ),
            ),
        ),
        operations=(PluginOperation(
            operation_id="recalculate",
            label="Пересчитать",
            description="Перестраивает отчёт",
            ai_description="Recalculate the capacity report from current inputs.",
            confirmation_text="Пересчитать отчёт?",
            handler=execute,
            idempotent=True,
        ),),
        render=render,
    ))
    yield container, calls
    container.opencode_manager.stop()


def test_plugin_projects_all_shared_fields_dynamic_widgets_and_references(
    plugin_container,
) -> None:
    container, _calls = plugin_container
    catalog = container.plugins.list_plugins()
    assert catalog == [{
        "id": "reports.capacity",
        "title": "Capacity report",
        "description": "Корпоративный отчёт",
        "category": "Отчёты",
        "icon": "puzzle",
        "keywords": [
            "reports.capacity", "Capacity report", "Корпоративный отчёт",
            "Отчёты", "capacity", "нагрузка",
        ],
        "operation_count": 1,
    }]

    document = container.plugins.describe("reports.capacity", "test_int")
    category = next(field for field in document["fields"] if field["key"] == "category")
    assert category["visible"] is False
    assert category["reference"]["endpoint"] == (
        "/api/v1/plugins/reports.capacity/fields/category/options"
    )
    assert document["initial_values"] == {"enabled": False, "count": 2}
    assert [widget["kind"] for widget in document["widgets"]] == ["metric", "chart"]

    state = container.plugins.state(
        "reports.capacity",
        "test_int",
        {"enabled": True, "count": 4},
        document["version"],
    )
    category = next(field for field in state["fields"] if field["key"] == "category")
    assert category["visible"] is True
    assert {item["id"] for item in category["options"]} >= {"internal", "external"}


def test_plugin_operation_requires_browser_confirmation_and_receives_services(
    plugin_container,
) -> None:
    container, calls = plugin_container
    document = container.plugins.describe("reports.capacity", "test_int")
    first = container.plugins.run_operation(
        "reports.capacity",
        "recalculate",
        "test_int",
        {"enabled": False, "count": 2},
        document["version"],
    )
    assert first["confirmation_required"] is True
    assert calls == []

    result = container.plugins.run_operation(
        "reports.capacity",
        "recalculate",
        "test_int",
        {"enabled": False, "count": 2},
        document["version"],
        first["confirmation_token"],
    )
    assert result["success"] is True
    assert result["values"]["count"] == 3
    assert {field["key"] for field in result["fields"]} == {
        "enabled", "count", "category",
    }
    assert result["widgets"][0]["kind"] == "text"
    assert calls[0]["environment"] == "test_int"
    assert calls[0]["service"] is not None


def test_plugin_ai_policy_is_fail_closed_and_drives_exact_mcp_tools(
    plugin_container,
) -> None:
    container, calls = plugin_container
    operation_tool = plugin_operation_tool_name(
        "reports.capacity", "recalculate"
    )
    assert container.plugin_ai_policy.snapshot()["ai_visible"] is False
    assert operation_tool not in {
        tool["name"] for tool in available_tools(container)
    }

    policy = container.plugin_ai_policy.update({
        "ai_visible": True,
        "plugins": [{
            "id": "reports.capacity",
            "visible": True,
            "operations": {"recalculate": "manual"},
        }],
    })
    assert policy["plugins"][0]["operations"][0]["policy"] == "manual"
    allowed, manual = container.plugin_ai_policy.copilot_tools()
    assert allowed == (
        "list_plugins",
        "get_plugin_page",
        "calculate_plugin_state",
        "search_plugin_reference_options",
        "validate_plugin_values",
    )
    assert manual == (operation_tool,)
    tools = {tool["name"]: tool for tool in available_tools(container)}
    assert tools[operation_tool]["annotations"]["destructiveHint"] is True

    page = MCPTools(container).call(
        "get_plugin_page",
        {"plugin_id": "reports.capacity", "environment": "test_int"},
    )
    state = MCPTools(container).call("calculate_plugin_state", {
        "plugin_id": "reports.capacity",
        "environment": "test_int",
        "values": {"enabled": True, "count": 1},
        "plugin_version": page["version"],
    })
    assert next(
        field for field in state["fields"] if field["key"] == "category"
    )["visible"] is True
    options = MCPTools(container).call("search_plugin_reference_options", {
        "plugin_id": "reports.capacity",
        "field_path": "category",
        "environment": "test_int",
        "values": {"enabled": True, "count": 1},
        "query": "Внутр",
    })
    assert options["items"][0]["id"] == "internal"
    validation = MCPTools(container).call("validate_plugin_values", {
        "plugin_id": "reports.capacity",
        "environment": "test_int",
        "values": {"enabled": True, "count": 1, "category": "internal"},
        "plugin_version": page["version"],
    })
    assert validation["valid"] is True
    result = MCPTools(container).call(operation_tool, {
        "environment": "test_int",
        "values": {"enabled": False, "count": 1},
        "plugin_version": page["version"],
    })
    assert result["success"] is True
    # AI permission is handled by OpenCode before MCP dispatch, therefore the
    # browser-only confirmation token is not requested a second time.
    assert len(calls) == 1

    container.plugin_ai_policy.update({
        "ai_visible": True,
        "plugins": [{
            "id": "reports.capacity",
            "visible": True,
            "operations": {"recalculate": "deny"},
        }],
    })
    assert operation_tool not in {
        tool["name"] for tool in available_tools(container)
    }
    # Even a stale OpenCode session cannot bypass a policy changed to deny:
    # the dynamic tool disappears from discovery and dispatch fails closed.
    with pytest.raises(PermissionError, match="запрещена для AI"):
        MCPTools(container).call(operation_tool, {})


def test_plugin_registry_rejects_duplicate_id() -> None:
    registry = PluginRegistry()
    registry.register(PluginDefinition("corp.status", "Статус"))

    with pytest.raises(ValueError, match="уже зарегистрирован"):
        registry.register(PluginDefinition("corp.status", "Другой статус"))


def test_plugin_widget_boundary_rejects_active_or_external_image(
    plugin_container,
) -> None:
    container, _calls = plugin_container
    container.plugin_registry.register(PluginDefinition(
        plugin_id="reports.unsafe-image",
        title="Unsafe image",
        render=lambda _context, _values: ({
            "widget_id": "external",
            "kind": "image",
            "src": "https://untrusted.example/pixel.png",
            "alt": "External image",
        },),
    ))

    with pytest.raises(ValueError, match="same-origin"):
        container.plugins.describe("reports.unsafe-image", "test_int")
