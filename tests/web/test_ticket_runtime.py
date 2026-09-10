from __future__ import annotations

from pathlib import Path

import pytest

from tickets import (
    TicketAction,
    TicketActionResult,
    TicketAttribute,
    TicketCard,
    TicketFilterDefinition,
    TicketFilterOption,
    TicketListConfiguration,
    TicketListItem,
    TicketPage,
    TicketSection,
    TicketSortDefinition,
    TicketUserError,
)
from webapp.container import ApplicationContainer
from webapp.settings import WebSettings
from webapp.ticket_runtime import TicketCardVersionConflict


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
        mcp_enabled=False,
    )


class FakeTicketProvider:
    def __init__(self) -> None:
        self.list_calls = []
        self.search_calls = []
        self.action_calls = []
        self.status = "В работе"

    def get_list_configuration(self, context):
        assert context.services.itsm is not None
        return TicketListConfiguration(
            description="Назначенные пользователю заявки",
            filters=(
                TicketFilterDefinition(
                    "status",
                    "Статус",
                    options=(
                        TicketFilterOption("active", "Активные"),
                        TicketFilterOption("done", "Завершённые"),
                    ),
                ),
                TicketFilterDefinition(
                    "types",
                    "Типы",
                    kind="multiselect",
                    options=(
                        TicketFilterOption("api", "API"),
                        TicketFilterOption("app", "Приложение"),
                    ),
                ),
            ),
            sorts=(
                TicketSortDefinition("updated", "По обновлению"),
                TicketSortDefinition("created", "По созданию"),
            ),
            default_sort="updated",
            page_size=20,
        )

    def load_current_tickets(self, context, request):
        self.list_calls.append((context.environment, request))
        return TicketPage(items=(self._item(),), total=1)

    def find_tickets(self, context, request):
        self.search_calls.append((context.environment, request))
        return TicketPage(items=(self._item(),), total=1)

    def load_ticket_card_by_id(self, context, ticket_id):
        assert context.environment == "test_int"
        return TicketCard(
            ticket_id=ticket_id,
            title="Создать API Orders",
            description="Описание корпоративной заявки",
            status=self.status,
            status_tone="info",
            updated_at="2026-09-10 10:30",
            sections=(TicketSection(
                "main",
                "Основное",
                (
                    TicketAttribute("author", "Автор", "Иван", copyable=True),
                    TicketAttribute(
                        "source",
                        "Открыть в ITSM",
                        "Ссылка",
                        url="https://itsm.example.invalid/ticket",
                    ),
                ),
            ),),
            actions=(TicketAction(
                "take",
                "Взять в работу",
                self.take,
                style="success",
                color="#147D64",
                confirmation_text="Взять заявку в работу?",
            ),),
        )

    def take(self, context, ticket_id):
        self.action_calls.append((context.environment, ticket_id))
        self.status = "Назначена мне"
        return TicketActionResult("Заявка назначена")

    @staticmethod
    def _item():
        return TicketListItem(
            "REQ-42",
            "Создать API Orders",
            status="В работе",
            status_tone="info",
            updated_at="2026-09-10 10:30",
            attributes=(TicketAttribute("type", "Тип", "Создание API"),),
        )


@pytest.fixture
def ticket_container(tmp_path: Path):
    container = ApplicationContainer(_settings(tmp_path))
    provider = FakeTicketProvider()
    container.ticket_provider = provider
    yield container, provider
    container.opencode_manager.stop()


def test_ticket_runtime_calls_current_list_and_search_with_normalized_request(
    ticket_container,
) -> None:
    container, provider = ticket_container
    configuration = container.tickets.configuration("test_int")
    assert configuration["enabled"] is True
    assert configuration["default_sort"] == "updated"
    assert configuration["filters"][1]["kind"] == "multiselect"

    current = container.tickets.query(
        environment="test_int",
        query="",
        filters={"status": "active", "types": ["api", "api"]},
        sort_key="updated",
        sort_direction="desc",
        offset=0,
        limit=20,
    )
    assert current["items"][0]["id"] == "REQ-42"
    assert provider.list_calls[0][1].filters == {
        "status": "active",
        "types": ["api"],
    }
    assert provider.search_calls == []

    container.tickets.query(
        environment="test_int",
        query=" orders ",
        filters={},
        sort_key="",
        sort_direction="desc",
        offset=0,
        limit=20,
    )
    assert provider.search_calls[0][1].query == "orders"
    assert provider.search_calls[0][1].sort_key == "updated"

    with pytest.raises(TicketUserError, match="Неизвестные фильтры"):
        container.tickets.query(
            environment="test_int",
            query="",
            filters={"private": "value"},
            sort_key="",
            sort_direction="desc",
            offset=0,
            limit=20,
        )


def test_ticket_card_projects_corporate_actions_and_requires_confirmation(
    ticket_container,
) -> None:
    container, provider = ticket_container
    card = container.tickets.card("REQ-42", "test_int")
    assert card["status"] == "В работе"
    assert card["actions"][0] == {
        "id": "take",
        "label": "Взять в работу",
        "description": "",
        "style": "success",
        "color": "#147D64",
        "confirmation_required": True,
        "disabled_reason": "",
    }
    assert "handler" not in card["actions"][0]

    confirmation = container.tickets.run_action(
        action_id="take",
        ticket_id="REQ-42",
        environment="test_int",
        card_version=card["version"],
    )
    assert confirmation["confirmation_required"] is True
    assert provider.action_calls == []

    result = container.tickets.run_action(
        action_id="take",
        ticket_id="REQ-42",
        environment="test_int",
        card_version=card["version"],
        confirmation_token=confirmation["confirmation_token"],
    )
    assert result["success"] is True
    assert result["message"] == "Заявка назначена"
    assert result["card"]["status"] == "Назначена мне"
    assert provider.action_calls == [("test_int", "REQ-42")]

    with pytest.raises(TicketCardVersionConflict):
        container.tickets.run_action(
            action_id="take",
            ticket_id="REQ-42",
            environment="test_int",
            card_version="stale-version",
        )


def test_ticket_workspace_is_explicitly_disabled_without_private_provider(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(_settings(tmp_path))
    try:
        assert container.tickets.configuration("test_int")["enabled"] is False
    finally:
        container.opencode_manager.stop()


def test_ticket_runtime_rejects_an_unknown_environment_before_calling_provider(
    ticket_container,
) -> None:
    container, provider = ticket_container
    with pytest.raises(TicketUserError, match="Неизвестное окружение"):
        container.tickets.query(
            environment="unknown",
            query="",
            filters={},
            sort_key="",
            sort_direction="desc",
            offset=0,
            limit=20,
        )
    assert provider.list_calls == []
