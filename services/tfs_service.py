"""Точка подключения корпоративной реализации Azure DevOps/TFS.

Репозиторий намеренно не содержит сетевой реализации, URL или правил auth.
"""
from __future__ import annotations

from typing import Any

from core.env_manager import EnvManager
from core.http_client import HttpClient
from opencode_integration.data_sources import DataSourceNotConfiguredError


class TfsService:
    def __init__(self, env_manager: EnvManager, http_client: HttpClient) -> None:
        self._env_manager = env_manager
        self._http_client = http_client

    def get_pull_request(self, reference: Any, environment: str = "") -> Any:
        """Вернуть реальные данные связанного PR; реализуется корпоративным кодом."""
        del reference, environment
        raise DataSourceNotConfiguredError(
            "Корпоративный источник Azure DevOps не подключён. "
            "Реализуйте TfsService.get_pull_request() в закрытом модуле."
        )
