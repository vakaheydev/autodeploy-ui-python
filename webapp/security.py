"""Small in-memory capability stores used for confirmations and polling."""
from __future__ import annotations

import copy
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional


def request_fingerprint(form_id: str, environment: str, values: Any, version: str) -> str:
    body = json.dumps(
        [form_id, environment, values, version],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


@dataclass
class _Confirmation:
    fingerprint: str
    expires_at: float


class ConfirmationStore:
    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, _Confirmation] = {}
        self._lock = threading.Lock()

    def issue(self, fingerprint: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_locked()
            self._items[token] = _Confirmation(fingerprint, time.monotonic() + self._ttl)
        return token

    def consume(self, token: str, fingerprint: str) -> bool:
        with self._lock:
            self._purge_locked()
            item = self._items.pop(token, None)
            return bool(item and secrets.compare_digest(item.fingerprint, fingerprint))

    def _purge_locked(self) -> None:
        now = time.monotonic()
        for token in [key for key, item in self._items.items() if item.expires_at < now]:
            self._items.pop(token, None)


@dataclass
class SubmissionState:
    submission_id: str
    form_id: str
    environment: str
    response: Any
    payload: Any
    created_at: float
    polling: bool


class SubmissionStore:
    def __init__(self, ttl_seconds: float = 24 * 3600.0) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, SubmissionState] = {}
        self._lock = threading.Lock()

    def create(
        self, form_id: str, environment: str, response: Any, payload: Any, polling: bool
    ) -> SubmissionState:
        submission_id = secrets.token_urlsafe(24)
        state = SubmissionState(
            submission_id=submission_id,
            form_id=form_id,
            environment=environment,
            response=copy.deepcopy(response),
            payload=copy.deepcopy(payload),
            created_at=time.time(),
            polling=polling,
        )
        with self._lock:
            self._purge_locked()
            self._items[submission_id] = state
        return state

    def get(self, submission_id: str) -> Optional[SubmissionState]:
        with self._lock:
            self._purge_locked()
            item = self._items.get(submission_id)
            return copy.deepcopy(item) if item else None

    def update(self, state: SubmissionState) -> None:
        with self._lock:
            if state.submission_id in self._items:
                self._items[state.submission_id] = copy.deepcopy(state)

    def _purge_locked(self) -> None:
        threshold = time.time() - self._ttl
        for key in [key for key, item in self._items.items() if item.created_at < threshold]:
            self._items.pop(key, None)
