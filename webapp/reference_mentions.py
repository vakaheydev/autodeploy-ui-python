"""Cache-only reference mentions for the web Copilot composer."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from core.reference_cache import CachedReferenceEntry
from forms.fields import ReferenceConfig
from opencode_integration.context_builder import is_secret_key, sanitize


_MAX_PUBLIC_VALUE_CHARS = 2_000


@dataclass(frozen=True)
class _MentionCatalog:
    id: str
    reference: ReferenceConfig
    origins: tuple[str, ...]


@dataclass(frozen=True)
class _MentionRecord:
    catalog: _MentionCatalog
    cache_resource: str
    cached_at: float
    identifier: str
    label: str
    search_fields: tuple[tuple[str, str], ...]
    context: Mapping[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog.id,
            "cache_resource": self.cache_resource,
            "catalog_label": " · ".join(self.catalog.origins),
            "resource": self.catalog.reference.resource,
            "identifier": self.identifier,
            "label": self.label,
            "search_fields": [
                {"key": key, "value": value}
                for key, value in self.search_fields
            ],
            "cached_at": self.cached_at,
        }


class ReferenceMentionService:
    """Indexes only data already present in ``ReferenceCache``.

    No resolver or reference handler is reachable from this class.  An expired
    cache entry remains searchable until another explicit application action
    refreshes or invalidates it.
    """

    def __init__(self, container: Any) -> None:
        self.container = container
        self._lock = threading.RLock()
        self._indexes: dict[
            str, tuple[int, tuple[_MentionCatalog, ...], tuple[_MentionRecord, ...]]
        ] = {}

    def search(self, environment: str, query: str, limit: int = 20) -> dict[str, Any]:
        self.container.forms._ensure_environment(environment)
        clean_query = " ".join(str(query).split()).casefold()
        records = self._records(environment)
        ranked: list[tuple[int, str, str, _MentionRecord]] = []
        for record in records:
            rank = self._match_rank(record, clean_query)
            if rank is None:
                continue
            ranked.append((rank, record.label.casefold(), record.identifier, record))
        ranked.sort(key=lambda item: item[:3])
        selected = [item[3] for item in ranked[: max(1, min(int(limit), 50))]]
        return {
            "items": [item.public() for item in selected],
            "cache_only": True,
            "environment": environment,
            "truncated": len(ranked) > len(selected),
        }

    def resolve(
        self,
        environment: str,
        pointers: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Resolve client pointers against the current cache snapshot only."""
        if not pointers:
            return []
        self.container.forms._ensure_environment(environment)
        records = {
            (item.catalog.id, item.cache_resource, item.identifier): item
            for item in self._records(environment)
        }
        resolved: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for pointer in pointers:
            key = (
                str(pointer.get("catalog_id") or ""),
                str(pointer.get("cache_resource") or ""),
                str(pointer.get("identifier") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            record = records.get(key)
            if record is None:
                raise ValueError(
                    "Выбранный @-объект больше не найден в кэше текущего "
                    "окружения. Откройте список и выберите его заново."
                )
            resolved.append({
                "catalog": " · ".join(record.catalog.origins),
                "environment": environment,
                "resource": record.catalog.reference.resource,
                "identifier": record.identifier,
                "label": record.label,
                "cached_at": record.cached_at,
                "search_fields": dict(record.search_fields),
                "cached_object": dict(record.context),
            })
        return resolved

    def _records(self, environment: str) -> tuple[_MentionRecord, ...]:
        catalogs = self._catalogs()
        revision = self.container.reference_cache.revision
        with self._lock:
            cached = self._indexes.get(environment)
            if cached is not None and cached[0] == revision and cached[1] == catalogs:
                return cached[2]

        entries = self.container.reference_cache.read_entries(environment)
        records = self._build_records(catalogs, entries)
        with self._lock:
            self._indexes[environment] = (revision, catalogs, records)
        return records

    def _catalogs(self) -> tuple[_MentionCatalog, ...]:
        result: list[_MentionCatalog] = []
        for kind, reference in sorted(self.container.search_catalogs.items()):
            if is_secret_key(reference.value_key) or is_secret_key(reference.label_key):
                continue
            identity = self._reference_identity(reference)
            encoded = json.dumps(
                (kind, identity), ensure_ascii=False, separators=(",", ":")
            )
            result.append(_MentionCatalog(
                id=hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20],
                reference=reference,
                origins=({"api": "API", "application": "Приложения"}.get(kind, kind),),
            ))
        return tuple(sorted(result, key=lambda item: item.id))

    @classmethod
    def _build_records(
        cls,
        catalogs: Sequence[_MentionCatalog],
        entries: Sequence[CachedReferenceEntry],
    ) -> tuple[_MentionRecord, ...]:
        deduplicated: dict[tuple[str, str], _MentionRecord] = {}
        for catalog in catalogs:
            reference = catalog.reference
            search_keys = tuple(dict.fromkeys(
                key for key in (reference.search_keys or (reference.label_key,))
                if not is_secret_key(key)
            ))
            public_keys = tuple(dict.fromkeys((
                reference.value_key,
                reference.label_key,
                *search_keys,
            )))
            for entry in entries:
                if not cls._resource_matches(reference.resource, entry.resource):
                    continue
                for item in entry.data:
                    raw_identifier = item.get(reference.value_key)
                    raw_label = item.get(reference.label_key)
                    if raw_identifier in (None, "") or raw_label in (None, ""):
                        continue
                    identifier = cls._display_value(raw_identifier)
                    label = cls._display_value(raw_label)
                    fields = tuple(
                        (key, cls._display_value(item.get(key)))
                        for key in search_keys
                        if item.get(key) not in (None, "")
                    )
                    context = {
                        key: cls._safe_value(item[key], key)
                        for key in public_keys
                        if key in item and not is_secret_key(key)
                    }
                    record = _MentionRecord(
                        catalog=catalog,
                        cache_resource=entry.resource,
                        cached_at=entry.timestamp,
                        identifier=identifier,
                        label=label,
                        search_fields=fields,
                        context=context,
                    )
                    key = (catalog.id, identifier)
                    previous = deduplicated.get(key)
                    if previous is None or previous.cached_at < record.cached_at:
                        deduplicated[key] = record
        return tuple(deduplicated.values())

    @staticmethod
    def _reference_identity(reference: ReferenceConfig) -> tuple[Any, ...]:
        return (
            reference.source,
            reference.resource,
            reference.value_key,
            reference.label_key,
            tuple(reference.search_keys),
            tuple(reference.detail_keys),
        )

    @staticmethod
    def _resource_matches(configured: str, cached: str) -> bool:
        safe = str(configured).replace("/", "_").replace("\\", "_")
        return cached in {configured, safe} or cached.startswith(f"{configured}__") \
            or cached.startswith(f"{safe}__")

    @staticmethod
    def _display_value(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()[:1_000]
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:1_000]
        except (TypeError, ValueError):
            return str(value)[:1_000]

    @staticmethod
    def _safe_value(value: Any, key: str) -> Any:
        clean = sanitize(value, key=key)
        try:
            rendered = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            rendered = str(clean)
        if len(rendered) <= _MAX_PUBLIC_VALUE_CHARS:
            return clean
        return rendered[:_MAX_PUBLIC_VALUE_CHARS] + "…"

    @staticmethod
    def _match_rank(record: _MentionRecord, query: str) -> int | None:
        if not query:
            return 3
        # Keep mention lookup identical to the owning ReferenceConfig contract.
        # label/value are searchable only when the corporate declaration puts
        # those keys into search_keys (or when label_key is the fallback).
        values = [value for _, value in record.search_fields]
        folded = [value.casefold() for value in values]
        if query in folded:
            return 0
        if any(value.startswith(query) for value in folded):
            return 1
        if any(query in value for value in folded):
            return 2
        return None
