"""
ReferenceCache — кеш HTTP-справочников в памяти.

Ключ кеша: (resource, environment) — чтобы одно имя ресурса не смешивало
данные разных окружений.
Инвалидация: по TTL при каждом обращении.
"""
import time
from typing import Dict, List, Optional, Tuple


class ReferenceCache:
    """
    Хранит загруженные справочники в памяти до истечения TTL.
    TTL задаётся снаружи (берётся из config/reference_cache_config.py).
    """

    def __init__(self) -> None:
        # (resource, environment) → (timestamp, data)
        self._store: Dict[Tuple[str, str], Tuple[float, List[Dict]]] = {}

    def get(
        self, resource: str, environment: str, ttl: int
    ) -> Optional[List[Dict]]:
        """
        Возвращает закешированные данные, если они не устарели.
        Возвращает None, если кеш пуст или TTL истёк.
        """
        entry = self._store.get((resource, environment))
        if entry is None:
            return None
        ts, data = entry
        if time.monotonic() - ts > ttl:
            del self._store[(resource, environment)]
            return None
        return data

    def set(self, resource: str, environment: str, data: List[Dict]) -> None:
        """Сохраняет данные в кеш с текущей меткой времени."""
        self._store[(resource, environment)] = (time.monotonic(), data)

    def invalidate(
        self, resource: Optional[str] = None, environment: Optional[str] = None
    ) -> None:
        """
        Ручная инвалидация:
        - без аргументов — очищает весь кеш
        - resource — все окружения этого ресурса
        - resource + environment — конкретная запись
        """
        if resource is None:
            self._store.clear()
            return
        keys = [
            k for k in self._store
            if k[0] == resource and (environment is None or k[1] == environment)
        ]
        for k in keys:
            del self._store[k]
