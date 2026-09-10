"""Контракты корпоративных источников данных для AI-автозаполнения.

В этом репозитории намеренно нет HTTP URL, авторизации или маппинга ITSM/ADO.
Корпоративный код реализует минимальные data-source протоколы и при
необходимости опциональный ``ITSMAIPromptProvider``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class DataSourceNotConfiguredError(RuntimeError):
    """Корпоративный адаптер не подключён к демонстрационной сборке."""


@dataclass(frozen=True)
class ITSMAIPromptRequest:
    """Safe context passed to an optional corporate ticket-prompt hook.

    ``ticket_context`` has already passed through the public redaction layer.
    ``form_id`` is empty while the main Copilot still has to choose a form and
    is populated for an exact-form ``fetch_from_itsm`` workflow.
    """

    ticket_id: str
    environment: str
    ticket_context: Any
    form_id: str = ""


@dataclass(frozen=True)
class ITSMAIPrompt:
    """Trusted corporate guidance selected for one ITSM request type.

    Corporate code should return static, reviewed instructions selected by
    ``ticket_type``. It must never copy arbitrary ticket prose into
    ``instructions`` because this result is placed in a trusted prompt section.
    """

    ticket_type: str
    instructions: str


@runtime_checkable
class ITSMDataSource(Protocol):
    def get_ticket(self, ticket_id: str, environment: str) -> Any:
        """Вернуть фактические данные одной заявки в JSON-совместимом виде."""
        ...


@runtime_checkable
class ITSMAIPromptProvider(Protocol):
    """Optional capability implemented by a corporate ITSM service."""

    def get_ai_prompt(
        self, request: ITSMAIPromptRequest
    ) -> ITSMAIPrompt | None:
        """Return trusted mapping guidance for this request, or ``None``."""
        ...


@runtime_checkable
class AzureDevOpsDataSource(Protocol):
    def get_pull_request(self, reference: Any, environment: str) -> Any:
        """Вернуть PR, комментарии и нужные метаданные в JSON-совместимом виде."""
        ...
