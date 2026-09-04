"""Единственная заменяемая точка получения ITSM-заявки.

В корпоративной сборке достаточно изменить эту маленькую функцию. Очистка
секретов, поиск связанного PR и ограничение контекста выполняются отдельно в
``ContextBuilder`` и поэтому не зависят от способа получения заявки.
"""
from __future__ import annotations

from typing import Any

from opencode_integration.data_sources import ITSMDataSource


def sanitaze_request(
    itsm_service: ITSMDataSource,
    ticket_id: str,
    environment: str,
) -> Any:
    """Получить одну заявку через подключённый корпоративный ITSM-адаптер."""
    return itsm_service.get_ticket(ticket_id, environment)


def sanitize_request(
    itsm_service: ITSMDataSource,
    ticket_id: str,
    environment: str,
) -> Any:
    """Корректно написанный публичный alias для ``sanitaze_request``."""
    return sanitaze_request(itsm_service, ticket_id, environment)
