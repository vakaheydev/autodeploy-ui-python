from __future__ import annotations

import threading
from typing import Any

from opencode_integration.form_search import (
    SemanticFormSearchSession,
    validate_semantic_search,
)


class _SearchClient:
    timeout = 120.0

    def __init__(self) -> None:
        self.created = 0
        self.contexts: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def require_agent(self, name: str, timeout: float) -> None:
        assert name == "form-search"
        assert timeout == 10.0

    def require_provider(self, provider_id: str, timeout: float) -> None:
        assert provider_id == "corp"
        assert timeout == 10.0

    def create_session(self, _title: str, **kwargs: Any) -> str:
        self.created += 1
        assert kwargs["variant"] == "none"
        assert kwargs["mcp_names"] == ()
        return "semantic-session"

    def add_session_context(self, **kwargs: Any) -> None:
        self.contexts.append(kwargs)

    def send_structured_message(self, **kwargs: Any) -> dict[str, Any]:
        self.messages.append(kwargs)
        return {
            "candidates": [{
                "form_id": "api.create",
                "score": 94,
                "reason": "Запрошено создание API",
            }]
        }

    def abort_session(self, _session_id: str) -> None:
        return None

    def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)


def test_catalog_and_search_session_are_lazy_and_reused(monkeypatch) -> None:
    calls = 0

    def catalog(_forms):
        nonlocal calls
        calls += 1
        return [{
            "form_id": "api.create",
            "title": "Создание API",
            "category": "api",
            "purpose": "Создать API",
            "use_when": ["нужно новое API"],
            "avoid_when": [],
        }]

    monkeypatch.setattr("opencode_integration.form_search.build_form_catalog", catalog)
    client = _SearchClient()
    search = SemanticFormSearchSession(client, forms=(object(),))  # type: ignore[arg-type]

    assert calls == 0
    assert search.session_id is None

    first = search.search(
        "создай API",
        provider_id="corp",
        model_id="weak-model",
        none_variant="none",
    )
    second = search.search(
        "ещё одно API",
        provider_id="corp",
        model_id="weak-model",
        none_variant="none",
    )

    assert calls == 1
    assert client.created == 1
    assert len(client.contexts) == 1
    assert "TRUSTED_FORM_CATALOG" in client.contexts[0]["prompt"]
    assert '"fields"' not in client.contexts[0]["prompt"]
    assert "routing-only catalog" in client.contexts[0]["prompt"]
    assert len(client.messages) == 2
    assert all(item["variant"] == "none" for item in client.messages)
    assert "enum" not in client.messages[0]["schema"]["properties"]["candidates"]["items"]["properties"]["form_id"]
    assert first.session_id == second.session_id == "semantic-session"
    assert first.candidates[0].description["title"] == "Создание API"

    search.close()
    assert client.deleted == ["semantic-session"]


def test_active_search_can_be_aborted_without_waiting_for_model(monkeypatch) -> None:
    monkeypatch.setattr("opencode_integration.form_search.build_form_catalog", lambda _forms: [{
        "form_id": "api.create",
        "title": "Создание API",
        "category": "api",
        "purpose": "Создать API",
        "use_when": ["нужно новое API"],
        "avoid_when": [],
    }])

    class BlockingClient(_SearchClient):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.released = threading.Event()
            self.aborted = threading.Event()

        def send_structured_message(self, **kwargs: Any) -> dict[str, Any]:
            self.messages.append(kwargs)
            self.entered.set()
            assert self.released.wait(2)
            return {"candidates": []}

        def abort_session(self, _session_id: str) -> None:
            self.aborted.set()
            self.released.set()

    client = BlockingClient()
    search = SemanticFormSearchSession(client, forms=(object(),))  # type: ignore[arg-type]
    worker = threading.Thread(target=lambda: search.search(
        "создай API",
        provider_id="corp",
        model_id="weak-model",
        none_variant="none",
    ))
    worker.start()
    assert client.entered.wait(1)

    search.cancel()

    assert client.aborted.wait(0.2)
    worker.join(2)
    assert not worker.is_alive()


def test_search_result_is_deduplicated_sorted_and_trimmed_locally() -> None:
    catalog = [
        {"form_id": "a", "title": "A"},
        {"form_id": "b", "title": "B"},
        {"form_id": "c", "title": "C"},
    ]
    result = validate_semantic_search(
        {"candidates": [
            {"form_id": "a", "score": 40, "reason": "weak"},
            {"form_id": "b", "score": 90, "reason": "best"},
            {"form_id": "a", "score": 80, "reason": "better duplicate"},
            {"form_id": "c", "score": 70, "reason": "third"},
            {"form_id": "invented", "score": 100, "reason": "not in catalog"},
        ]},
        catalog=catalog,
        limit=2,
    )

    assert [(item.form_id, item.score) for item in result] == [("b", 90), ("a", 80)]
