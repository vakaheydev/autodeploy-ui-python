"""Контракты корпоративных источников данных для AI-автозаполнения.

В этом репозитории намеренно нет HTTP URL, авторизации или маппинга ITSM/ADO.
Корпоративный код должен реализовать эти два небольших протокола и передать
объекты в ``Application``/``ContextBuilder``.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class DataSourceNotConfiguredError(RuntimeError):
    """Корпоративный адаптер не подключён к демонстрационной сборке."""


@runtime_checkable
class ITSMDataSource(Protocol):
    def get_ticket(self, ticket_id: str, environment: str) -> Any:
        """Вернуть фактические данные одной заявки в JSON-совместимом виде."""
        ...


@runtime_checkable
class AzureDevOpsDataSource(Protocol):
    def get_pull_request(self, reference: Any, environment: str) -> Any:
        """Вернуть PR, комментарии и нужные метаданные в JSON-совместимом виде."""
        ...
