"""
HttpReferenceHandler — загрузка справочников с HTTP сервера с кешированием.

TTL кеша задаётся в config/reference_cache_config.py.
Ресурсы без записи в конфиге не кешируются.
"""
from typing import Any, Callable, Dict, List, Optional

from config.environments import ITSM_LOGIN_KEY, ITSM_PASSWORD_KEY, TFS_TOKEN_KEY, gravitee_token_key
from config.reference_cache_config import CACHE_TTL
from core.env_manager import EnvManager
from core.http_client import HttpClient
from core.reference_cache import ReferenceCache
from forms.fields import ReferenceConfig
from handlers.base_reference_handler import BaseReferenceHandler


# Тип авторизации для каждого ресурса.
# "gravitee" → Bearer GRAVITEE_TOKEN_<ENV_KEY> из .env
# "tfs"      → Bearer TFS_TOKEN из .env
# "itsm"     → Basic ITSM_LOGIN:ITSM_PASSWORD из .env
# Ресурсы без записи запрашиваются без авторизации.
_AUTH_MAP: Dict[str, str] = {
    "gravitee_apis": "gravitee",
}

# TODO: заменить заглушки реальными URL для каждого окружения
# Структура: resource_key → {env_key: url}
_URL_MAP: Dict[str, Dict[str, str]] = {
    "gravitee_apis": {
        "test_int":    "https://api.test-int.example.com/management/v2/apis",
        "test_ext":    "https://api.test-ext.example.com/management/v2/apis",
        "regress_int": "https://api.regress-int.example.com/management/v2/apis",
        "regress_ext": "https://api.regress-ext.example.com/management/v2/apis",
        "prod_int":    "https://api.prod-int.example.com/management/v2/apis",
        "prod_ext":    "https://api.prod-ext.example.com/management/v2/apis",
    },
}

# Необязательные постпроцессоры для конкретных ресурсов.
# Преобразуют/распаковывают сырой HTTP-ответ в плоский List[Dict].
# Сигнатура: (raw_response: Any) -> List[Dict]
_RESPONSE_PROCESSORS: Dict[str, Callable[[Any], List[Dict]]] = {
    "gravitee_apis": lambda resp: resp.get("data", []),
}

# Необязательные фильтры по окружению.
# Вызываются ПОСЛЕ _RESPONSE_PROCESSORS, уже на готовом списке элементов.
# Сигнатура: (environment: str, items: List[Dict]) -> List[Dict]
#
# Пример — разделить приложения по окружению:
#   "applications": lambda env, items: [
#       item for item in items
#       if ("regress" in item.get("name", "").lower()) == env.startswith("regress")
#   ],
_FILTER_MAP: Dict[str, Callable[[str, List[Dict]], List[Dict]]] = {
}


class HttpReferenceHandler(BaseReferenceHandler):
    """
    Загружает справочные данные через HTTP с кешированием в памяти.

    Авторизация: тип токена берётся из _AUTH_MAP по ключу resource.
    TTL кеша берётся из CACHE_TTL по ключу resource.
    """

    def __init__(
        self, http_client: HttpClient, cache: ReferenceCache, env_manager: EnvManager
    ) -> None:
        self._client = http_client
        self._cache = cache
        self._env_manager = env_manager

    def supports(self, config: ReferenceConfig) -> bool:
        return config.source == "http"

    def load(
        self, config: ReferenceConfig, environment: str = ""
    ) -> List[Dict[str, Any]]:
        resource = config.resource
        ttl = CACHE_TTL.get(resource)

        if ttl is not None:
            cached = self._cache.get(resource, environment, ttl)
            if cached is not None:
                return cached

        self._set_auth(resource, environment)

        url = self._resolve_url(resource, environment)
        if not url:
            print(
                f"[HttpReferenceHandler] URL не задан для resource='{resource}'"
                f" / environment='{environment}'. Возвращаю пустой список."
            )
            return []

        try:
            raw = self._client.get(url)
        except Exception as exc:
            print(f"[HttpReferenceHandler] Ошибка загрузки {url}: {exc}")
            return []

        items = self._process_response(resource, raw)
        items = self._filter_items(resource, environment, items)

        if ttl is not None:
            self._cache.set(resource, environment, items)

        return items

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _set_auth(self, resource: str, environment: str) -> None:
        """Устанавливает авторизацию на HttpClient согласно _AUTH_MAP."""
        auth_type = _AUTH_MAP.get(resource)
        if auth_type == "gravitee":
            token = self._env_manager.get(gravitee_token_key(environment))
            self._client.set_token(token)
        elif auth_type == "tfs":
            token = self._env_manager.get(TFS_TOKEN_KEY)
            self._client.set_token(token)
        elif auth_type == "itsm":
            login    = self._env_manager.get(ITSM_LOGIN_KEY)
            password = self._env_manager.get(ITSM_PASSWORD_KEY)
            self._client.set_basic_auth(login, password)
        else:
            self._client.set_token("")

    def _resolve_url(self, resource: str, environment: str) -> str:
        """Возвращает URL для ресурса в заданном окружении."""
        return _URL_MAP.get(resource, {}).get(environment, "")

    def _filter_items(
        self, resource: str, environment: str, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Применяет env-фильтр из _FILTER_MAP, если он зарегистрирован."""
        fn = _FILTER_MAP.get(resource)
        return fn(environment, items) if fn is not None else items

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
