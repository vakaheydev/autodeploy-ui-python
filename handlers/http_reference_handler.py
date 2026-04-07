"""
HttpReferenceHandler — загрузка справочников с HTTP сервера.

TODO: заполнить _URL_MAP реальными эндпоинтами справочников.
TODO: при необходимости добавить кэширование и фоновую загрузку (threading).
"""
from typing import Any, Callable, Dict, List, Optional

from core.http_client import HttpClient
from forms.fields import ReferenceConfig
from handlers.base_reference_handler import BaseReferenceHandler


# TODO: заменить заглушки реальными URL для каждого окружения
# Структура: resource_key → {env_key: url}
_URL_MAP: Dict[str, Dict[str, str]] = {
    # Пример:
    # "gravitee_apis": {
    #     "test_int":    "https://api.test-int.example.com/management/v2/apis",
    #     "prod_int":    "https://api.prod-int.example.com/management/v2/apis",
    # },
}

# Необязательные постпроцессоры для конкретных ресурсов.
# Позволяют трансформировать/фильтровать ответ сервера.
# Сигнатура: (raw_response: Any) -> List[Dict]
_RESPONSE_PROCESSORS: Dict[str, Callable[[Any], List[Dict]]] = {
    # "gravitee_apis": lambda resp: resp.get("data", []),
}


class HttpReferenceHandler(BaseReferenceHandler):
    """
    Загружает справочные данные через HTTP.

    Принимает HttpClient снаружи (Dependency Injection),
    что позволяет использовать актуальный токен окружения.
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._client = http_client

    def supports(self, config: ReferenceConfig) -> bool:
        return config.source == "http"

    def load(
        self, config: ReferenceConfig, environment: str = ""
    ) -> List[Dict[str, Any]]:
        url = self._resolve_url(config.resource, environment)
        if not url:
            print(
                f"[HttpReferenceHandler] URL не задан для resource='{config.resource}'"
                f" / environment='{environment}'. Возвращаю пустой список."
            )
            return []

        try:
            raw = self._client.get(url)
        except Exception as exc:
            print(f"[HttpReferenceHandler] Ошибка загрузки {url}: {exc}")
            return []

        items = self._process_response(config.resource, raw)
        return items

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _resolve_url(self, resource: str, environment: str) -> str:
        """Возвращает URL для ресурса в заданном окружении."""
        return _URL_MAP.get(resource, {}).get(environment, "")

    def _process_response(
        self, resource: str, raw: Any
    ) -> List[Dict[str, Any]]:
        """Применяет постпроцессор если он зарегистрирован, иначе пытается угадать структуру."""
        if resource in _RESPONSE_PROCESSORS:
            return _RESPONSE_PROCESSORS[resource](raw)
        # Автоопределение: список или обёртка с data/items
        if isinstance(raw, list):
            return raw
        for key in ("data", "items", "content", "results"):
            if isinstance(raw, dict) and key in raw:
                return raw[key]
        return []
