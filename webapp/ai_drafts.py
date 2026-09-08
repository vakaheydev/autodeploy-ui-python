"""Persistent, non-submitting form drafts backed by the Python form runtime.

Manual edits and AI proposals intentionally share this store and representation.
Drafts live in the per-user data directory until the operator submits or deletes
them; the browser is never the system of record.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from forms.fields import FieldDefinition, FieldType
from opencode_integration.reference_resolver import LocalReferenceResolver
from webapp.form_runtime import form_version


CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}
_PLURAL_SEGMENT_RE = re.compile(r"^(?P<base>[A-Za-z_][A-Za-z0-9_-]*?)_(?P<index>\d+)$")
_BRACKET_INDEX_RE = re.compile(r"\[(?P<index>\d+)\]")
_log = logging.getLogger("web.drafts")


@dataclass(frozen=True)
class DraftProposal:
    field_path: str
    value: Any
    confidence: str
    source: str
    reason: str = ""
    conflict: str = ""


@dataclass
class FormDraft:
    id: str
    workflow_id: str
    form_id: str
    environment: str
    form_version: str
    baseline: dict[str, Any]
    values: dict[str, Any]
    fields: list[dict[str, Any]]
    warnings: list[str]
    errors: list[dict[str, Any]]
    valid: bool
    created_at: float
    updated_at: float
    expires_at: float
    source: str = "ai"
    revision: int = 1
    status: str = "complete"
    progress: str = "Черновик готов"
    error: str = ""
    request_fingerprint: str = ""
    pending_baseline: Optional[dict[str, Any]] = field(default=None, repr=False)
    pending_field_paths: tuple[str, ...] = field(default=(), repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "workflow_id": self.workflow_id,
                "form_id": self.form_id,
                "environment": self.environment,
                "form_version": self.form_version,
                "revision": self.revision,
                "status": self.status,
                "progress": self.progress,
                "error": self.error,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "expires_at": self.expires_at,
                "source": self.source,
                "result": {
                    "values": copy.deepcopy(self.values),
                    "baseline": copy.deepcopy(self.baseline),
                    "fields": copy.deepcopy(self.fields),
                    "warnings": list(self.warnings),
                    "errors": copy.deepcopy(self.errors),
                    "valid": self.valid,
                },
            }


class FormDraftStore:
    """Thread-safe draft capabilities; no method performs form submission."""

    def __init__(
        self,
        container: Any,
        *,
        path: Optional[Path] = None,
        ttl_seconds: float = 0,
    ) -> None:
        self.container = container
        # Kept as a compatibility attribute for private extensions. A value of
        # zero means persistent-until-deleted and is the public web default.
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._drafts: dict[str, FormDraft] = {}
        self._fingerprints: dict[str, str] = {}
        self._lock = threading.RLock()
        configured_path = path
        if configured_path is None:
            settings = getattr(container, "settings", None)
            data_dir = getattr(settings, "data_dir", None)
            if data_dir is not None:
                configured_path = Path(data_dir) / "drafts.json"
        self._path = configured_path.resolve() if configured_path is not None else None
        self._load()

    def begin_ai_fill(
        self,
        *,
        workflow_id: str,
        form_id: str,
        environment: str,
        version: str,
        current_values: Mapping[str, Any],
    ) -> FormDraft:
        """Create the durable draft that Copilot will fill asynchronously."""
        if not workflow_id:
            raise ValueError("AI-черновик требует workflow_id")
        form = self.container.forms.get_form(form_id, environment)
        actual_version = form_version(form)
        if version != actual_version:
            raise ValueError("Версия формы устарела; обновите страницу")
        validation = self.container.forms.validate(
            form_id,
            environment,
            current_values,
            actual_version,
            validate_references=False,
        )
        now = time.time()
        draft = FormDraft(
            id=secrets.token_urlsafe(24),
            workflow_id=workflow_id,
            form_id=form_id,
            environment=environment,
            form_version=actual_version,
            baseline=copy.deepcopy(validation.values),
            values=copy.deepcopy(validation.values),
            fields=[],
            warnings=[],
            errors=[dict(item) for item in validation.errors],
            valid=validation.valid,
            created_at=now,
            updated_at=now,
            expires_at=self._expires_at(now),
            source="ai",
            status="running",
            progress="Copilot анализирует данные заявки…",
        )
        with self._lock:
            self._prune_locked(now)
            self._drafts[draft.id] = draft
            self._persist_locked()
        return draft

    def prepare(
        self,
        *,
        workflow_id: str,
        form_id: str,
        environment: str,
        version: str,
        proposals: Sequence[Mapping[str, Any]],
        draft_id: str = "",
        current_values: Optional[Mapping[str, Any]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> FormDraft:
        self._check_cancel(cancel_event)
        if not 1 <= len(proposals) <= 100:
            raise ValueError("Черновик должен содержать от 1 до 100 предложений")
        form = self.container.forms.get_form(form_id, environment)
        actual_version = form_version(form)
        if version != actual_version:
            raise ValueError(
                "Версия формы устарела; повторно вызовите get_form_schema"
            )
        document = self.container.forms.describe(form_id, environment)
        existing = self.get(draft_id) if draft_id else None
        initial_ai_fill = bool(
            existing is not None
            and existing.status == "running"
            and not existing.fields
            and existing.pending_baseline is None
        )
        if existing is not None:
            if existing.workflow_id != workflow_id:
                raise PermissionError("Черновик относится к другой AI-сессии")
            if (existing.form_id, existing.environment) != (form_id, environment):
                raise ValueError("Нельзя изменить форму или окружение существующего черновика")
        baseline = copy.deepcopy(document["initial_values"])
        working_values = copy.deepcopy(baseline)
        previous_fields: dict[str, dict[str, Any]] = {}
        if existing is not None:
            with existing.lock:
                original_baseline = copy.deepcopy(existing.baseline)
                working_values.update(copy.deepcopy(
                    existing.pending_baseline
                    if existing.pending_baseline is not None
                    else existing.values
                ))
                pending_paths = (
                    existing.pending_field_paths
                    or tuple(str(item.get("key", "")) for item in existing.fields)
                )
                previous_fields = {
                    str(item.get("key", "")): copy.deepcopy(item)
                    for item in existing.fields
                    if str(item.get("key", "")) in pending_paths
                }
            baseline = copy.deepcopy(working_values)
            for path in pending_paths:
                self._restore_path(baseline, original_baseline, path)
        if current_values is not None:
            working_values.update(copy.deepcopy(dict(current_values)))
            if existing is None:
                baseline.update(copy.deepcopy(dict(current_values)))

        fingerprint = self._fingerprint(
            workflow_id=workflow_id,
            form_id=form_id,
            environment=environment,
            version=version,
            baseline={"review": baseline, "working": working_values},
            proposals=proposals,
        )
        if existing is not None and existing.request_fingerprint == fingerprint:
            self._check_cancel(cancel_event)
            with existing.lock:
                existing.baseline = baseline
                existing.pending_baseline = None
                existing.pending_field_paths = ()
                existing.status = "complete"
                existing.progress = "Черновик уже актуален"
                existing.error = ""
                existing.updated_at = time.time()
                existing.expires_at = self._expires_at(existing.updated_at)
            self._persist()
            return existing
        if existing is None:
            with self._lock:
                self._prune_locked(time.time())
                duplicate_id = self._fingerprints.get(fingerprint)
                duplicate = self._drafts.get(duplicate_id or "")
            if duplicate is not None:
                return duplicate

        definitions = self._field_definitions(form.fields)
        parsed = self._parse_proposals(proposals, definitions)
        semantic_values = copy.deepcopy(working_values)
        for proposal in parsed:
            self._set_path(semantic_values, proposal.field_path, copy.deepcopy(proposal.value))

        top_level = [field.key for field in form.fields]
        proposal_by_top: dict[str, DraftProposal] = {}
        for proposal in parsed:
            proposal_by_top.setdefault(proposal.field_path.split(".", 1)[0], proposal)
        payload = {
            "form": semantic_values,
            "meta": {
                "warnings": [],
                "sources": {
                    key: (
                        proposal_by_top[key].source if key in proposal_by_top else None
                    )
                    for key in top_level
                },
                "confidence": {
                    key: (
                        proposal_by_top[key].confidence
                        if key in proposal_by_top
                        else "unknown"
                    )
                    for key in top_level
                },
                "reasons": {
                    key: (
                        proposal_by_top[key].reason or None
                        if key in proposal_by_top
                        else "Поле не предлагалось AI"
                    )
                    for key in top_level
                },
                "conflicts": [
                    {
                        "field": proposal.field_path.split(".", 1)[0],
                        "message": proposal.conflict,
                        "sources": [proposal.source],
                    }
                    for proposal in parsed
                    if proposal.conflict
                ],
            },
        }
        resolver = LocalReferenceResolver(self.container.new_reference_resolver())
        resolved = resolver.resolve(
            payload,
            form=form,
            environment=environment,
            current_values=working_values,
            cancel_event=cancel_event,
        )
        validation = self.container.forms.validate(
            form_id,
            environment,
            resolved.payload["form"],
            actual_version,
        )
        resolved_values = validation.values
        meta = resolved.payload["meta"]
        parsed_by_path = {proposal.field_path: proposal for proposal in parsed}
        review_paths = list(previous_fields)
        review_paths.extend(
            proposal.field_path
            for proposal in parsed
            if proposal.field_path not in previous_fields
        )
        fields: list[dict[str, Any]] = []
        for path in review_paths:
            proposal = parsed_by_path.get(path)
            previous = previous_fields.get(path, {})
            field_def = self._definition_for_path(definitions, path)
            top = path.split(".", 1)[0]
            fields.append({
                "key": path,
                "label": field_def.label,
                "current_value": copy.deepcopy(
                    self._get_path(baseline, path)
                ),
                "proposed_value": copy.deepcopy(
                    self._get_path(resolved_values, path)
                ),
                "confidence": (
                    str(meta["confidence"].get(top, proposal.confidence))
                    if proposal is not None
                    else str(previous.get("confidence") or "unknown")
                ),
                "source": (
                    meta["sources"].get(top) or proposal.source
                    if proposal is not None
                    else previous.get("source")
                ),
                "reason": (
                    meta["reasons"].get(top) or proposal.reason or None
                    if proposal is not None
                    else previous.get("reason")
                ),
                "conflict": (
                    proposal.conflict or None
                    if proposal is not None
                    else previous.get("conflict")
                ),
                "candidates": [
                    list(item)
                    for item in resolved.candidates.get(
                        path,
                        resolved.candidates.get(
                            top,
                            previous.get("candidates") or (),
                        ),
                    )
                ],
            })
        warnings = list(dict.fromkeys([
            *resolved.warnings,
            *(
                [
                    "Есть незаполненные или некорректные поля; исправьте их перед отправкой."
                ]
                if validation.errors
                else []
            ),
            *[
                f"Низкая уверенность: {item['label']}"
                for item in fields
                if item["confidence"] == "low"
            ],
        ]))
        now = time.time()
        self._check_cancel(cancel_event)
        if existing is None:
            draft = FormDraft(
                id=secrets.token_urlsafe(24),
                workflow_id=workflow_id,
                form_id=form_id,
                environment=environment,
                form_version=actual_version,
                baseline=baseline,
                values=copy.deepcopy(resolved_values),
                fields=fields,
                warnings=warnings,
                errors=[dict(item) for item in validation.errors],
                valid=validation.valid,
                created_at=now,
                updated_at=now,
                expires_at=self._expires_at(now),
                request_fingerprint=fingerprint,
            )
            with self._lock:
                self._prune_locked(now)
                self._drafts[draft.id] = draft
                self._fingerprints[fingerprint] = draft.id
                self._persist_locked()
            return draft

        with existing.lock:
            previous_fingerprint = existing.request_fingerprint
            existing.baseline = baseline
            existing.values = copy.deepcopy(resolved_values)
            existing.fields = fields
            existing.warnings = warnings
            existing.errors = [dict(item) for item in validation.errors]
            existing.valid = validation.valid
            existing.updated_at = now
            existing.expires_at = self._expires_at(now)
            existing.revision += 1
            existing.status = "complete"
            existing.progress = (
                "Черновик Copilot готов"
                if initial_ai_fill
                else "Уточнённый черновик готов"
            )
            existing.error = ""
            existing.request_fingerprint = fingerprint
            existing.pending_baseline = None
            existing.pending_field_paths = ()
        with self._lock:
            if self._fingerprints.get(previous_fingerprint) == existing.id:
                self._fingerprints.pop(previous_fingerprint, None)
            self._fingerprints[fingerprint] = existing.id
            self._persist_locked()
        return existing

    def get(self, draft_id: str) -> Optional[FormDraft]:
        if not draft_id:
            return None
        with self._lock:
            return self._drafts.get(draft_id)

    def require(self, draft_id: str) -> FormDraft:
        value = self.get(draft_id)
        if value is None:
            raise KeyError("Черновик не найден")
        return value

    def begin_refinement(
        self,
        draft_id: str,
        *,
        current_values: Mapping[str, Any],
        pending_fields: Sequence[str] = (),
    ) -> FormDraft:
        draft = self.require(draft_id)
        with draft.lock:
            if draft.status == "running":
                raise RuntimeError("Уточнение черновика уже выполняется")
            known = {str(item.get("key", "")) for item in draft.fields}
            requested = tuple(dict.fromkeys(
                str(item).strip() for item in pending_fields if str(item).strip()
            ))
            unknown = sorted(set(requested) - known)
            if unknown:
                raise ValueError(
                    "Неизвестные поля review: " + ", ".join(unknown)
                )
            draft.pending_baseline = copy.deepcopy(dict(current_values))
            draft.pending_field_paths = requested or tuple(
                str(item.get("key", "")) for item in draft.fields
            )
            draft.status = "running"
            draft.progress = "Copilot применяет уточнение…"
            draft.error = ""
            draft.updated_at = time.time()
            draft.expires_at = self._expires_at(draft.updated_at)
        self._persist()
        return draft

    def fail(self, draft_id: str, message: str) -> None:
        draft = self.get(draft_id)
        if draft is None:
            return
        with draft.lock:
            draft.status = "error"
            draft.progress = "Copilot не подготовил черновик"
            draft.error = str(message)[:2000]
            draft.updated_at = time.time()
            draft.pending_baseline = None
            draft.pending_field_paths = ()
        self._persist()

    def delete(self, draft_id: str, *, workflow_id: str = "") -> None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise KeyError("AI-черновик не найден")
            if workflow_id and draft.workflow_id != workflow_id:
                raise PermissionError("Черновик относится к другой AI-сессии")
            del self._drafts[draft_id]
            if self._fingerprints.get(draft.request_fingerprint) == draft_id:
                self._fingerprints.pop(draft.request_fingerprint, None)
            self._persist_locked()

    def delete_workflow(self, workflow_id: str) -> None:
        """Retain drafts when a chat ends; kept for extension compatibility."""
        del workflow_id

    def save_values(
        self,
        *,
        form_id: str,
        environment: str,
        version: str,
        values: Mapping[str, Any],
        draft_id: str = "",
        clear_review: bool = False,
        pending_review_fields: Optional[Sequence[str]] = None,
    ) -> FormDraft:
        """Create or update a user-editable draft without submitting anything."""
        form = self.container.forms.get_form(form_id, environment)
        actual_version = form_version(form)
        if version != actual_version:
            raise ValueError("Версия формы устарела; обновите страницу")
        validation = self.container.forms.validate(
            form_id,
            environment,
            values,
            version,
            validate_references=False,
        )
        now = time.time()
        existing = self.get(draft_id) if draft_id else None
        if existing is not None and (
            existing.form_id != form_id or existing.environment != environment
        ):
            raise ValueError("Черновик относится к другой форме или окружению")
        pending_review: Optional[set[str]] = None
        if existing is not None and pending_review_fields is not None:
            pending_review = {
                str(item).strip()
                for item in pending_review_fields
                if str(item).strip()
            }
            with existing.lock:
                known = {str(item.get("key") or "") for item in existing.fields}
            unknown = sorted(pending_review - known)
            if unknown:
                raise ValueError("Неизвестные поля review: " + ", ".join(unknown))
        if existing is None:
            document = self.container.forms.describe(form_id, environment)
            draft = FormDraft(
                id=secrets.token_urlsafe(24),
                workflow_id="",
                form_id=form_id,
                environment=environment,
                form_version=actual_version,
                baseline=copy.deepcopy(document["initial_values"]),
                values=copy.deepcopy(validation.values),
                fields=[],
                warnings=[],
                errors=[dict(item) for item in validation.errors],
                valid=validation.valid,
                created_at=now,
                updated_at=now,
                expires_at=0,
                source="manual",
                progress="Черновик сохранён",
            )
            with self._lock:
                self._drafts[draft.id] = draft
                self._persist_locked()
            return draft
        with existing.lock:
            existing.values = copy.deepcopy(validation.values)
            existing.errors = [dict(item) for item in validation.errors]
            existing.valid = validation.valid
            existing.form_version = actual_version
            existing.updated_at = now
            existing.expires_at = 0
            existing.revision += 1
            existing.status = "complete"
            existing.progress = "Черновик сохранён"
            existing.error = ""
            existing.pending_baseline = None
            existing.pending_field_paths = ()
            if clear_review:
                existing.baseline = copy.deepcopy(validation.values)
                existing.fields = []
                existing.warnings = []
            elif pending_review is not None:
                existing.fields = [
                    item for item in existing.fields
                    if str(item.get("key") or "") in pending_review
                ]
                if not existing.fields:
                    existing.baseline = copy.deepcopy(validation.values)
                    existing.warnings = []
        self._persist()
        return existing

    def save_ai_result(
        self,
        *,
        workflow_id: str,
        form_id: str,
        environment: str,
        version: str,
        baseline: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> FormDraft:
        """Persist the legacy Extractor result in the same durable draft store."""
        actual_version = form_version(
            self.container.forms.get_form(form_id, environment)
        )
        if version != actual_version:
            raise ValueError("Версия формы устарела; повторите заполнение")
        now = time.time()
        values = copy.deepcopy(dict(result.get("values") or {}))
        validation = self.container.forms.validate(
            form_id,
            environment,
            values,
            version,
            validate_references=False,
        )
        draft = FormDraft(
            id=secrets.token_urlsafe(24),
            workflow_id=workflow_id,
            form_id=form_id,
            environment=environment,
            form_version=actual_version,
            baseline=copy.deepcopy(dict(baseline)),
            values=copy.deepcopy(validation.values),
            fields=copy.deepcopy(list(result.get("fields") or [])),
            warnings=[str(item) for item in result.get("warnings") or []],
            errors=[dict(item) for item in validation.errors],
            valid=validation.valid,
            created_at=now,
            updated_at=now,
            expires_at=0,
            source="ai",
            progress="Черновик Copilot готов",
        )
        with self._lock:
            self._drafts[draft.id] = draft
            self._persist_locked()
        return draft

    def list_all(self) -> list[FormDraft]:
        with self._lock:
            return sorted(
                self._drafts.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )

    def _expires_at(self, now: float) -> float:
        return now + self.ttl_seconds if self.ttl_seconds > 0 else 0

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("draft storage root must be a list")
            loaded: dict[str, FormDraft] = {}
            for raw in payload:
                if not isinstance(raw, Mapping):
                    continue
                draft_id = str(raw.get("id") or "").strip()
                form_id = str(raw.get("form_id") or "").strip()
                environment = str(raw.get("environment") or "").strip()
                if not draft_id or not form_id or not environment:
                    continue
                status = str(raw.get("status") or "complete")
                interrupted = status == "running"
                if interrupted:
                    status = "error"
                draft = FormDraft(
                    id=draft_id,
                    workflow_id=str(raw.get("workflow_id") or ""),
                    form_id=form_id,
                    environment=environment,
                    form_version=str(raw.get("form_version") or ""),
                    baseline=copy.deepcopy(dict(raw.get("baseline") or {})),
                    values=copy.deepcopy(dict(raw.get("values") or {})),
                    fields=copy.deepcopy(list(raw.get("fields") or [])),
                    warnings=[str(item) for item in raw.get("warnings") or []],
                    errors=copy.deepcopy(list(raw.get("errors") or [])),
                    valid=bool(raw.get("valid")),
                    created_at=float(raw.get("created_at") or time.time()),
                    updated_at=float(raw.get("updated_at") or time.time()),
                    expires_at=0,
                    source=str(raw.get("source") or "ai"),
                    revision=max(1, int(raw.get("revision") or 1)),
                    status=status,
                    progress=(
                        "AI-операция была прервана перезапуском"
                        if interrupted
                        else str(raw.get("progress") or "Черновик сохранён")
                    ),
                    error=(
                        "Сервер был перезапущен до завершения Copilot"
                        if interrupted
                        else str(raw.get("error") or "")
                    ),
                    request_fingerprint=str(raw.get("request_fingerprint") or ""),
                )
                loaded[draft.id] = draft
            self._drafts = loaded
            self._fingerprints = {
                item.request_fingerprint: item.id
                for item in loaded.values()
                if item.request_fingerprint
            }
        except Exception as exc:
            _log.warning(
                "Draft storage read failed file=%s error_type=%s",
                self._path.name,
                type(exc).__name__,
            )

    def _persist(self) -> None:
        with self._lock:
            self._persist_locked()

    def _persist_locked(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        for draft in sorted(self._drafts.values(), key=lambda item: item.updated_at):
            with draft.lock:
                records.append({
                    "id": draft.id,
                    "workflow_id": draft.workflow_id,
                    "form_id": draft.form_id,
                    "environment": draft.environment,
                    "form_version": draft.form_version,
                    "baseline": copy.deepcopy(draft.baseline),
                    "values": copy.deepcopy(draft.values),
                    "fields": copy.deepcopy(draft.fields),
                    "warnings": list(draft.warnings),
                    "errors": copy.deepcopy(draft.errors),
                    "valid": draft.valid,
                    "created_at": draft.created_at,
                    "updated_at": draft.updated_at,
                    "expires_at": 0,
                    "source": draft.source,
                    "revision": draft.revision,
                    "status": draft.status,
                    "progress": draft.progress,
                    "error": draft.error,
                    "request_fingerprint": draft.request_fingerprint,
                })
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(records, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        try:
            temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(temporary, self._path)

    def _prune_locked(self, now: float) -> None:
        removed = {
            key: value
            for key, value in self._drafts.items()
            if value.expires_at > 0 and value.expires_at < now
        }
        self._drafts = {
            key: value
            for key, value in self._drafts.items()
            if value.expires_at <= 0 or value.expires_at >= now
        }
        for draft in removed.values():
            if self._fingerprints.get(draft.request_fingerprint) == draft.id:
                self._fingerprints.pop(draft.request_fingerprint, None)
        # Persistent drafts are deliberately not capped: lifecycle is explicit
        # (successful submit or manual delete), not an arbitrary LRU policy.

    @staticmethod
    def _fingerprint(
        *,
        workflow_id: str,
        form_id: str,
        environment: str,
        version: str,
        baseline: Mapping[str, Any],
        proposals: Sequence[Mapping[str, Any]],
    ) -> str:
        encoded = json.dumps(
            {
                "workflow_id": workflow_id,
                "form_id": form_id,
                "environment": environment,
                "version": version,
                "baseline": baseline,
                "proposals": list(proposals),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _parse_proposals(
        cls,
        values: Sequence[Mapping[str, Any]],
        definitions: Mapping[str, FieldDefinition],
    ) -> tuple[DraftProposal, ...]:
        result: list[DraftProposal] = []
        seen: set[str] = set()
        for raw in values:
            if not isinstance(raw, Mapping):
                raise ValueError("Каждое предложение поля должно быть объектом")
            unknown = set(raw) - {
                "field_path", "value", "confidence", "source", "reason", "conflict"
            }
            if unknown:
                raise ValueError(
                    "Неизвестные свойства предложения: " + ", ".join(sorted(unknown))
                )
            raw_path = str(raw.get("field_path", "")).strip()
            if not raw_path:
                raise ValueError("Пути предложений должны быть непустыми и уникальными")
            path = cls._normalize_proposal_path(definitions, raw_path)
            field_def = cls._definition_for_path(definitions, path)
            confidence = str(raw.get("confidence", "unknown")).strip().casefold()
            if confidence not in CONFIDENCE_VALUES:
                raise ValueError(f"Некорректная уверенность для поля {path}")
            source = str(raw.get("source", "")).strip()
            if not source:
                raise ValueError(f"Для поля {path} требуется источник")
            expanded = cls._expand_block_proposal(
                definitions,
                path,
                field_def,
                raw.get("value"),
            )
            for expanded_path, expanded_value in expanded:
                if expanded_path in seen:
                    raise ValueError(
                        "Пути предложений должны быть непустыми и уникальными"
                    )
                result.append(DraftProposal(
                    field_path=expanded_path,
                    value=copy.deepcopy(expanded_value),
                    confidence=confidence,
                    source=source[:500],
                    reason=str(raw.get("reason", "")).strip()[:1000],
                    conflict=str(raw.get("conflict", "")).strip()[:1000],
                ))
                seen.add(expanded_path)
        return tuple(result)

    @classmethod
    def _expand_block_proposal(
        cls,
        definitions: Mapping[str, FieldDefinition],
        path: str,
        field_def: FieldDefinition,
        value: Any,
    ) -> list[tuple[str, Any]]:
        """Turn object/array-valued block proposals into reviewable leaf paths.

        OpenCode may conveniently propose every repeated instance as an array
        at ``plan`` or one complete object at ``plan_2``. The UI reviews
        individual values, so persist known children as ``plan_2.name``,
        ``plan_2.type`` and so on. Empty or non-object block values stay
        addressable at block level for backwards compatibility and useful
        validation errors.
        """
        if field_def.field_type != FieldType.BLOCK:
            return [(path, value)]
        if (
            field_def.plural
            and isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray, Mapping))
        ):
            instances = list(value)
            if not instances:
                raise ValueError(
                    f"Массив повторяемого блока {path} не должен быть пустым"
                )
            if path.rsplit(".", 1)[-1] != field_def.key:
                raise ValueError(
                    f"Массив допустим только для базового пути блока {field_def.key}"
                )
            if (
                field_def.plural_max is not None
                and len(instances) > field_def.plural_max
            ):
                raise ValueError(f"Превышено число значений поля {path}")
            result: list[tuple[str, Any]] = []
            for position, instance in enumerate(instances, start=1):
                if not isinstance(instance, Mapping):
                    raise ValueError(
                        f"Каждый элемент повторяемого блока {path} должен быть объектом"
                    )
                instance_path = cls._plural_instance_path(path, position)
                result.extend(cls._expand_block_proposal(
                    definitions,
                    instance_path,
                    field_def,
                    instance,
                ))
            return result
        if not isinstance(value, Mapping) or not value:
            return [(path, value)]
        result: list[tuple[str, Any]] = []
        for child_key, child_value in value.items():
            child_path = cls._normalize_proposal_path(
                definitions, f"{path}.{child_key}"
            )
            child_def = cls._definition_for_path(definitions, child_path)
            result.extend(cls._expand_block_proposal(
                definitions,
                child_path,
                child_def,
                child_value,
            ))
        return result

    @classmethod
    def _normalize_proposal_path(
        cls,
        definitions: Mapping[str, FieldDefinition],
        path: str,
    ) -> str:
        """Accept common zero-based AI index syntax for repeated fields.

        The legacy form model stores the first instance at ``plan`` and later
        instances at ``plan_2``, ``plan_3``. Models naturally emit
        ``plan[0]`` or ``plan.0``. Normalize both at the MCP boundary so a weak
        model does not need to reproduce the storage convention perfectly.
        """
        dotted = _BRACKET_INDEX_RE.sub(lambda match: f".{match.group('index')}", path)
        if "[" in dotted or "]" in dotted:
            raise ValueError(f"Неизвестное поле формы: {path}")
        segments = dotted.split(".")
        concrete: list[str] = []
        indexed_previous = False
        for segment in segments:
            if not segment:
                raise ValueError(f"Неизвестное поле формы: {path}")
            if segment.isdigit():
                if not concrete or indexed_previous:
                    raise ValueError(f"Неизвестное поле формы: {path}")
                current_path = ".".join(concrete)
                current_def = cls._definition_for_path(definitions, current_path)
                if not current_def.plural:
                    raise ValueError(f"Поле {current_path} не является повторяемым")
                position = int(segment) + 1
                if (
                    current_def.plural_max is not None
                    and position > current_def.plural_max
                ):
                    raise ValueError(f"Превышено число значений поля {current_path}")
                if position > 1:
                    concrete[-1] = f"{concrete[-1]}_{position}"
                indexed_previous = True
                continue
            concrete.append(segment)
            indexed_previous = False
        normalized = ".".join(concrete)
        cls._definition_for_path(definitions, normalized)
        return normalized

    @staticmethod
    def _plural_instance_path(path: str, position: int) -> str:
        if position <= 1:
            return path
        parent, separator, key = path.rpartition(".")
        instance = f"{key}_{position}"
        return f"{parent}{separator}{instance}" if separator else instance

    @classmethod
    def _definition_for_path(
        cls,
        definitions: Mapping[str, FieldDefinition],
        path: str,
    ) -> FieldDefinition:
        direct = definitions.get(path)
        if direct is not None:
            return direct
        canonical: list[str] = []
        for segment in path.split("."):
            candidate = ".".join((*canonical, segment))
            if candidate in definitions:
                canonical.append(segment)
                continue
            match = _PLURAL_SEGMENT_RE.fullmatch(segment)
            if match is None:
                raise ValueError(f"Неизвестное поле формы: {path}")
            base_path = ".".join((*canonical, match.group("base")))
            base = definitions.get(base_path)
            if base is None or not base.plural:
                raise ValueError(f"Неизвестное поле формы: {path}")
            maximum = base.plural_max
            if maximum is not None and int(match.group("index")) > maximum:
                raise ValueError(f"Превышено число значений поля {base_path}")
            canonical.append(match.group("base"))
        resolved = definitions.get(".".join(canonical))
        if resolved is not None:
            return resolved
        raise ValueError(f"Неизвестное поле формы: {path}")

    @classmethod
    def _field_definitions(
        cls,
        fields: Iterable[FieldDefinition],
        prefix: str = "",
    ) -> dict[str, FieldDefinition]:
        result: dict[str, FieldDefinition] = {}
        for field_def in fields:
            path = f"{prefix}.{field_def.key}" if prefix else field_def.key
            result[path] = field_def
            if field_def.field_type == FieldType.BLOCK:
                result.update(cls._field_definitions(field_def.block_fields, path))
        return result

    @staticmethod
    def _get_path(values: Mapping[str, Any], path: str) -> Any:
        current: Any = values
        for part in path.split("."):
            if not isinstance(current, Mapping):
                return None
            current = current.get(part)
        return current

    @staticmethod
    def _set_path(values: dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        current = values
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        current[parts[-1]] = value

    @classmethod
    def _restore_path(
        cls,
        target: dict[str, Any],
        baseline: Mapping[str, Any],
        path: str,
    ) -> None:
        marker = object()
        value: Any = baseline
        for part in path.split("."):
            if not isinstance(value, Mapping) or part not in value:
                value = marker
                break
            value = value[part]
        parts = path.split(".")
        current = target
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        if value is marker:
            current.pop(parts[-1], None)
        else:
            current[parts[-1]] = copy.deepcopy(value)

    @staticmethod
    def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Подготовка AI-черновика отменена")
