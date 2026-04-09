"""
Конфигурация кеширования HTTP-справочников.

Ключ — resource из ReferenceConfig (тот же, что в _URL_MAP).
Значение — TTL в секундах.
  Ресурсы без записи не кешируются (всегда свежий HTTP-запрос).
  TTL_INFINITE (-1) — кеш не протухает, обновляется только вручную кнопкой ↻.
"""
from typing import Dict

TTL_INFINITE: int = -1   # кеш живёт до ручного обновления

CACHE_TTL: Dict[str, int] = {
    "gravitee_apis": TTL_INFINITE,
}
