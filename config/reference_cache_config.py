"""
Конфигурация кеширования HTTP-справочников.

Ключ — resource из ReferenceConfig (тот же, что в _URL_MAP).
Значение — TTL в секундах. Ресурсы без записи не кешируются.
"""
from typing import Dict

CACHE_TTL: Dict[str, int] = {
    "gravitee_apis": 300,   # 5 минут
}
