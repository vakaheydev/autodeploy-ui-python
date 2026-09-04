"""Expiring, non-submitting AI form drafts backed by the Python form runtime."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from forms.fields import FieldDefinition, FieldType
from opencode_integration.reference_resolver import LocalReferenceResolver
from webapp.form_runtime import form_version


CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}
_PLURAL_PATH_RE = re.compile(r"^(?P<base>[A-Za-z_][A-Za-z0-9_.-]*?)_(?P<index>\d+)$")


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

    def __init__(self, container: Any, *, ttl_seconds: float = 24 * 3600) -> None:
        self.container = container
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self._drafts: dict[str, FormDraft] = {}
        self._fingerprints: dict[str, str] = {}
        self._lock = threading.RLock()

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
        form = self.container.forms.get_form(form_id)
        actual_version = form_version(form)
        if version != actual_version:
            raise ValueError(
                "Версия формы устарела; повторно вызовите get_form_schema"
            )
        document = self.container.forms.describe(form_id, environment)
        existing = self.get(draft_id) if draft_id else None
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
                existing.expires_at = existing.updated_at + self.ttl_seconds
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
                expires_at=now + self.ttl_seconds,
                request_fingerprint=fingerprint,
            )
            with self._lock:
                self._prune_locked(now)
                self._drafts[draft.id] = draft
                self._fingerprints[fingerprint] = draft.id
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
            existing.expires_at = now + self.ttl_seconds
            existing.revision += 1
            existing.status = "complete"
            existing.progress = "Уточнённый черновик готов"
            existing.error = ""
            existing.request_fingerprint = fingerprint
            existing.pending_baseline = None
            existing.pending_field_paths = ()
        with self._lock:
            if self._fingerprints.get(previous_fingerprint) == existing.id:
                self._fingerprints.pop(previous_fingerprint, None)
            self._fingerprints[fingerprint] = existing.id
        return existing

    def get(self, draft_id: str) -> Optional[FormDraft]:
        if not draft_id:
            return None
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            return self._drafts.get(draft_id)

    def require(self, draft_id: str) -> FormDraft:
        value = self.get(draft_id)
        if value is None:
            raise KeyError("AI-черновик не найден или истёк")
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
        return draft

    def fail(self, draft_id: str, message: str) -> None:
        draft = self.get(draft_id)
        if draft is None:
            return
        with draft.lock:
            draft.status = "error"
            draft.progress = "Уточнение не применено"
            draft.error = str(message)[:2000]
            draft.updated_at = time.time()
            draft.pending_baseline = None
            draft.pending_field_paths = ()

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

    def delete_workflow(self, workflow_id: str) -> None:
        with self._lock:
            removed = {
                key: value
                for key, value in self._drafts.items()
                if value.workflow_id == workflow_id
            }
            self._drafts = {
                key: value
                for key, value in self._drafts.items()
                if value.workflow_id != workflow_id
            }
            for draft in removed.values():
                if self._fingerprints.get(draft.request_fingerprint) == draft.id:
                    self._fingerprints.pop(draft.request_fingerprint, None)

    def _prune_locked(self, now: float) -> None:
        removed = {
            key: value
            for key, value in self._drafts.items()
            if value.expires_at < now
        }
        self._drafts = {
            key: value
            for key, value in self._drafts.items()
            if value.expires_at >= now
        }
        for draft in removed.values():
            if self._fingerprints.get(draft.request_fingerprint) == draft.id:
                self._fingerprints.pop(draft.request_fingerprint, None)
        if len(self._drafts) > 1000:
            ordered = sorted(self._drafts.values(), key=lambda item: item.updated_at)
            for item in ordered[: len(self._drafts) - 1000]:
                self._drafts.pop(item.id, None)
                if self._fingerprints.get(item.request_fingerprint) == item.id:
                    self._fingerprints.pop(item.request_fingerprint, None)

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
            path = str(raw.get("field_path", "")).strip()
            if not path or path in seen:
                raise ValueError("Пути предложений должны быть непустыми и уникальными")
            cls._definition_for_path(definitions, path)
            confidence = str(raw.get("confidence", "unknown")).strip().casefold()
            if confidence not in CONFIDENCE_VALUES:
                raise ValueError(f"Некорректная уверенность для поля {path}")
            source = str(raw.get("source", "")).strip()
            if not source:
                raise ValueError(f"Для поля {path} требуется источник")
            result.append(DraftProposal(
                field_path=path,
                value=copy.deepcopy(raw.get("value")),
                confidence=confidence,
                source=source[:500],
                reason=str(raw.get("reason", "")).strip()[:1000],
                conflict=str(raw.get("conflict", "")).strip()[:1000],
            ))
            seen.add(path)
        return tuple(result)

    @classmethod
    def _definition_for_path(
        cls,
        definitions: Mapping[str, FieldDefinition],
        path: str,
    ) -> FieldDefinition:
        direct = definitions.get(path)
        if direct is not None:
            return direct
        match = _PLURAL_PATH_RE.fullmatch(path)
        if match:
            base = definitions.get(match.group("base"))
            if base is not None and base.plural:
                maximum = base.plural_max
                if maximum is not None and int(match.group("index")) > maximum:
                    raise ValueError(f"Превышено число значений поля {match.group('base')}")
                return base
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
