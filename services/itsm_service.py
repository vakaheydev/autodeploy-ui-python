"""Точка подключения корпоративной реализации ITSM.

Репозиторий не знает URL, формат ответа или способ авторизации компании.
Замените тело ``get_ticket`` своей реализацией либо внедрите другой объект,
совместимый с ``ITSMDataSource``.
"""
from __future__ import annotations

from typing import Any

from core.env_manager import EnvManager
from core.http_client import HttpClient
from opencode_integration.data_sources import DataSourceNotConfiguredError


class ITSMService:
    def __init__(self, env_manager: EnvManager, http_client: HttpClient) -> None:
        self._env_manager = env_manager
        self._http_client = http_client

    def get_ticket(self, ticket_id: str, environment: str = "") -> Any:
        """Вернуть реальные данные заявки; реализуется в корпоративной сборке."""
        del ticket_id, environment
        raise DataSourceNotConfiguredError(
            "Корпоративный источник ITSM не подключён. "
            "Реализуйте ITSMService.get_ticket() в закрытом модуле."
        )
