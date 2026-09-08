from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.reference_cache import ReferenceCache
from forms.fields import ReferenceConfig
from forms.registry import FormRegistry
from webapp.reference_mentions import ReferenceMentionService


def _service(
    cache: ReferenceCache,
    monkeypatch: pytest.MonkeyPatch,
) -> ReferenceMentionService:
    monkeypatch.setattr(FormRegistry, "all_forms", lambda _self: [])
    reference = ReferenceConfig(
        source="corp_http",
        resource="gravitee_apis",
        value_key="id",
        label_key="name",
        search_keys=("context_path", "name", "id"),
        detail_keys=("owner", "access_token"),
    )

    def ensure_environment(environment: str) -> None:
        if environment not in {"test_int", "prod_int"}:
            raise ValueError("Неизвестное окружение")

    return ReferenceMentionService(SimpleNamespace(
        forms=SimpleNamespace(_ensure_environment=ensure_environment),
        reference_cache=cache,
        search_catalogs={"api": reference},
        plugin_registry=SimpleNamespace(all_plugins=lambda: []),
    ))


def test_mentions_search_only_configured_fields_in_current_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = ReferenceCache(tmp_path / "cache")
    cache.set("gravitee_apis", "test_int", [{
        "id": "api-test",
        "name": "Payments",
        "context_path": "/payments/v2",
        "owner": "Team Blue",
        "access_token": "must-not-leak",
    }])
    cache.set("gravitee_apis", "prod_int", [{
        "id": "api-prod",
        "name": "Production only",
        "context_path": "/prod",
    }])
    service = _service(cache, monkeypatch)

    result = service.search("test_int", "/payments", 20)

    assert result["cache_only"] is True
    assert [item["identifier"] for item in result["items"]] == ["api-test"]
    assert [item["key"] for item in result["items"][0]["search_fields"]] == [
        "context_path", "name", "id",
    ]
    assert service.search("test_int", "Team Blue", 20)["items"] == []
    assert service.search("test_int", "Production only", 20)["items"] == []


def test_mention_search_does_not_implicitly_add_label_or_identifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FormRegistry, "all_forms", lambda _self: [])
    cache = ReferenceCache(tmp_path / "cache")
    cache.set("applications", "test_int", [{
        "id": "app-hidden-id",
        "name": "Hidden label",
        "azp": "visible-azp",
    }])
    reference = ReferenceConfig(
        source="corp_http",
        resource="applications",
        value_key="id",
        label_key="name",
        search_keys=("azp",),
    )
    service = ReferenceMentionService(SimpleNamespace(
        forms=SimpleNamespace(_ensure_environment=lambda _environment: None),
        reference_cache=cache,
        search_catalogs={"application": reference},
        plugin_registry=SimpleNamespace(all_plugins=lambda: []),
    ))

    assert service.search("test_int", "visible-azp")["items"]
    assert service.search("test_int", "Hidden label")["items"] == []
    assert service.search("test_int", "app-hidden-id")["items"] == []


def test_expired_disk_entry_is_read_without_refresh_or_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    path = cache_dir / "gravitee_apis__test_int.json"
    path.write_text(json.dumps({
        "timestamp": 1,
        "data": [{"id": "stale-api", "name": "Stale API", "context_path": "/stale"}],
    }), encoding="utf-8")
    cache = ReferenceCache(cache_dir)
    service = _service(cache, monkeypatch)

    result = service.search("test_int", "stale", 20)

    assert result["items"][0]["identifier"] == "stale-api"
    assert result["items"][0]["cached_at"] == 1
    assert path.exists(), "cache-only lookup must not apply TTL or delete stale data"


def test_selected_pointer_is_resolved_against_cache_and_index_tracks_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = ReferenceCache(tmp_path / "cache")
    cache.set("gravitee_apis__tenant=blue", "test_int", [{
        "id": "api-1",
        "name": "Orders",
        "context_path": "/orders",
        "access_token": "must-not-leak",
    }])
    service = _service(cache, monkeypatch)
    item = service.search("test_int", "orders", 20)["items"][0]

    resolved = service.resolve("test_int", [{
        "catalog_id": item["catalog_id"],
        "cache_resource": item["cache_resource"],
        "identifier": item["identifier"],
    }])

    assert resolved[0]["identifier"] == "api-1"
    assert resolved[0]["cached_object"] == {
        "id": "api-1",
        "name": "Orders",
        "context_path": "/orders",
    }

    cache.set("gravitee_apis", "test_int", [{
        "id": "api-2", "name": "Billing", "context_path": "/billing",
    }])
    assert service.search("test_int", "billing", 20)["items"][0]["identifier"] == "api-2"

    with pytest.raises(ValueError, match="больше не найден"):
        service.resolve("test_int", [{
            "catalog_id": item["catalog_id"],
            "cache_resource": "gravitee_apis",
            "identifier": "missing",
        }])
