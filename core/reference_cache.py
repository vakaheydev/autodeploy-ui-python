"""
ReferenceCache — персистентный кеш HTTP-справочников.

Данные хранятся в памяти и продублированы в файлах папки cached/.
Формат файла: {"timestamp": <unix float>, "data": [...]}
Ключ кеша: (resource, environment) → файл cached/<resource>__<environment>.json
Инвалидация: по TTL при каждом обращении (проверяется timestamp в файле/памяти).
"""
import json
import logging
import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

_CACHE_DIR = Path(__file__).parent.parent / "cached"
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedReferenceEntry:
    """Immutable cache snapshot used by strictly cache-only readers."""

    resource: str
    environment: str
    timestamp: float
    data: tuple[Mapping[str, object], ...]


class ReferenceCache:
    """
    Загружает кеш из файлов при первом обращении к ресурсу,
    сохраняет в файлы при записи, удаляет файлы при инвалидации.
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self._cache_dir = Path(cache_dir or _CACHE_DIR).resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # (resource, environment) → (timestamp, data)
        self._store: Dict[Tuple[str, str], Tuple[float, List[Dict]]] = {}
        self._lock = threading.RLock()
        self._revision = 0

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def get(
        self, resource: str, environment: str, ttl: int
    ) -> Optional[List[Dict]]:
        """
        Возвращает данные, если они свежее TTL.
        Сначала проверяет память, затем файл.
        Возвращает None, если кеш отсутствует или устарел.

        ttl == -1 (TTL_INFINITE) — данные считаются актуальными всегда,
        пока кеш не сброшен вручную через invalidate().
        """
        with self._lock:
            return self._get_locked(resource, environment, ttl)

    def _get_locked(
        self, resource: str, environment: str, ttl: int
    ) -> Optional[List[Dict]]:
        key = (resource, environment)
        infinite = ttl == -1

        # 1. Проверяем память
        entry = self._store.get(key)
        if entry is not None:
            ts, data = entry
            if infinite or time.time() - ts <= ttl:
                return data
            del self._store[key]
            self._revision += 1

        # 2. Пробуем загрузить из файла
        file_entry = self._load_file(resource, environment)
        if file_entry is not None:
            ts, data = file_entry
            if infinite or time.time() - ts <= ttl:
                self._store[key] = (ts, data)   # восстанавливаем в памяти
                return data
            # Файл устарел — удаляем
            self._delete_file(resource, environment)
            self._revision += 1

        return None

    def get_timestamp(
        self, resource: str, environment: str
    ) -> Optional[float]:
        """
        Возвращает unix-timestamp последней записи кеша (memory → file).
        Возвращает None, если кеш отсутствует.
        """
        with self._lock:
            key = (resource, environment)
            entry = self._store.get(key)
            if entry is not None:
                return entry[0]

            file_entry = self._load_file(resource, environment)
            if file_entry is not None:
                ts, data = file_entry
                self._store[key] = (ts, data)
                return ts

            return None

    @property
    def revision(self) -> int:
        """Monotonic process-local revision for derived read-only indexes."""
        with self._lock:
            return self._revision

    def read_entries(self, environment: str) -> List[CachedReferenceEntry]:
        """Return every cached entry for ``environment`` without applying TTL.

        This is deliberately different from :meth:`get`: it never refreshes,
        invalidates or deletes an expired entry.  It is used by UI affordances
        that must stay fast and must not cause an unexpected corporate HTTP
        request, such as ``@`` references in the Copilot composer.
        """
        clean_environment = str(environment)
        safe_environment = self._safe_component(clean_environment)
        suffix = f"__{safe_environment}"
        with self._lock:
            snapshots: dict[str, CachedReferenceEntry] = {}
            seen_paths: set[Path] = set()

            for (resource, entry_environment), (timestamp, data) in self._store.items():
                if entry_environment != clean_environment:
                    continue
                path = self._cache_path(resource, entry_environment)
                seen_paths.add(path)
                snapshots[resource] = self._entry(
                    resource, entry_environment, timestamp, data
                )

            for path in sorted(self._cache_dir.glob(f"*{suffix}.json")):
                if path in seen_paths:
                    continue
                file_entry = self._load_path(path)
                if file_entry is None:
                    continue
                timestamp, data = file_entry
                resource = path.stem[:-len(suffix)]
                snapshots.setdefault(
                    resource,
                    self._entry(resource, clean_environment, timestamp, data),
                )

            return sorted(snapshots.values(), key=lambda item: item.resource)

    def set(self, resource: str, environment: str, data: List[Dict]) -> None:
        """Сохраняет данные в память и на диск."""
        with self._lock:
            ts = time.time()
            self._store[(resource, environment)] = (ts, data)
            self._save_file(resource, environment, ts, data)
            self._revision += 1

    def invalidate(
        self, resource: Optional[str] = None, environment: Optional[str] = None
    ) -> None:
        """
        Ручная инвалидация памяти и файлов:
        - без аргументов     — весь кеш
        - resource           — все окружения этого ресурса
        - resource+environment — конкретная запись
        """
        with self._lock:
            self._invalidate_locked(resource, environment)

    def _invalidate_locked(
        self, resource: Optional[str], environment: Optional[str]
    ) -> None:
        if resource is None:
            self._store.clear()
            for f in self._cache_dir.glob("*.json"):
                f.unlink(missing_ok=True)
            self._revision += 1
            return

        keys = [
            k for k in self._store
            if k[0] == resource and (environment is None or k[1] == environment)
        ]
        for k in keys:
            del self._store[k]

        if environment is not None:
            self._delete_file(resource, environment)
        else:
            for f in self._cache_dir.glob(f"{resource}__*.json"):
                f.unlink(missing_ok=True)
        self._revision += 1

    # ------------------------------------------------------------------
    # Работа с файлами
    # ------------------------------------------------------------------

    def _cache_path(self, resource: str, environment: str) -> Path:
        # Двойное подчёркивание как разделитель — resource и environment
        # не содержат __ в штатных именах
        safe_res = self._safe_component(resource)
        safe_env = self._safe_component(environment)
        return self._cache_dir / f"{safe_res}__{safe_env}.json"

    @staticmethod
    def _safe_component(value: str) -> str:
        return str(value).replace("/", "_").replace("\\", "_")

    @staticmethod
    def _entry(
        resource: str,
        environment: str,
        timestamp: float,
        data: List[Dict],
    ) -> CachedReferenceEntry:
        return CachedReferenceEntry(
            resource=resource,
            environment=environment,
            timestamp=float(timestamp),
            data=tuple(dict(item) for item in data if isinstance(item, Mapping)),
        )

    def _load_file(
        self, resource: str, environment: str
    ) -> Optional[Tuple[float, List[Dict]]]:
        path = self._cache_path(resource, environment)
        return self._load_path(path)

    def _load_path(self, path: Path) -> Optional[Tuple[float, List[Dict]]]:
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return float(raw["timestamp"]), list(raw["data"])
        except Exception as exc:
            _log.warning(
                "Reference cache read failed file=%s error_type=%s",
                path.name,
                type(exc).__name__,
            )
            return None

    def _save_file(
        self, resource: str, environment: str, ts: float, data: List[Dict]
    ) -> None:
        path = self._cache_path(resource, environment)
        try:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps({"timestamp": ts, "data": data}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temporary, path)
        except Exception as exc:
            _log.warning(
                "Reference cache write failed file=%s error_type=%s",
                path.name,
                type(exc).__name__,
            )

    def _delete_file(self, resource: str, environment: str) -> None:
        self._cache_path(resource, environment).unlink(missing_ok=True)
