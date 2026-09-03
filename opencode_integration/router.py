"""Безопасный выбор формы по очищенному контексту ITSM/ADO."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Sequence

from config.form_routing import build_form_catalog
from forms.base_form import BaseForm
from opencode_integration.client import OpenCodeCancelled, OpenCodeClient
from opencode_integration.context_builder import BuiltContext, ContextBuilder, contains_secret
from opencode_integration.data_sources import AzureDevOpsDataSource, ITSMDataSource
from opencode_integration.manager import FORM_ROUTER_AGENT
from opencode_integration.prompts import ROUTER_SYSTEM_RULES, build_routing_prompt
from opencode_integration.schemas import build_routing_schema

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover - окружение пользователя
    jsonschema = None  # type: ignore[assignment]
    _JSONSCHEMA_IMPORT_ERROR = exc
else:
    _JSONSCHEMA_IMPORT_ERROR = None


_log = logging.getLogger("opencode.router")
AUTO_SELECT_MIN_SCORE = 80
AUTO_SELECT_MIN_MARGIN = 15
_TICKET_TOKEN_RE = re.compile(r"(?<![\w])([A-Za-zА-Яа-я][\w]{0,19}[-_/]\d[\w-]{0,39})(?![\w])")
_DIGITS_RE = re.compile(r"(?<!\d)(\d{3,30})(?!\d)")


class FormRoutingError(ValueError):
    """Заявку нельзя безопасно направить в форму."""


@dataclass(frozen=True)
class RoutingCandidate:
    form_id: str
    score: int
    reason: str


@dataclass(frozen=True)
class RoutingDecision:
    selected_form_id: Optional[str]
    confidence: str
    reason: str
    candidates: tuple[RoutingCandidate, ...]
    question: str

    @property
    def needs_user_choice(self) -> bool:
        return self.selected_form_id is None


@dataclass(frozen=True)
class RoutingOutcome:
    context: BuiltContext
    decision: RoutingDecision


def extract_ticket_id(message: str) -> str:
    """Извлекает один номер заявки из короткой фразы пользователя."""
    text = str(message).strip()
    if not text:
        raise FormRoutingError("Укажите номер заявки")
    if len(text) > 500:
        raise FormRoutingError("Сообщение слишком длинное; укажите только номер заявки")
    if not any(char.isspace() for char in text) and len(text) <= 200:
        return text
    named_matches = [match.group(1) for match in _TICKET_TOKEN_RE.finditer(text)]
    matches = list(dict.fromkeys(
        named_matches
        if named_matches
        else [match.group(1) for match in _DIGITS_RE.finditer(text)]
    ))
    if len(matches) != 1:
        raise FormRoutingError("Не удалось однозначно определить номер заявки")
    return matches[0]


def validate_routing_output(
    payload: Any,
    *,
    form_ids: Sequence[str],
) -> RoutingDecision:
    """Повторно проверяет schema и применяет консервативную auto-select policy."""
    if jsonschema is None:
        raise RuntimeError(
            "Для AI-маршрутизации требуется пакет jsonschema из requirements.txt"
        ) from _JSONSCHEMA_IMPORT_ERROR
    schema = build_routing_schema(form_ids)
    validator_class = getattr(
        jsonschema,
        "Draft202012Validator",
        jsonschema.Draft7Validator,
    )
    validator = validator_class(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if errors:
        rendered = []
        for error in errors:
            path = ".".join(str(part) for part in error.absolute_path) or "$"
            rendered.append(f"{path}: {error.message}")
        raise FormRoutingError("Некорректный выбор формы:\n" + "\n".join(rendered))
    if contains_secret(payload):
        raise FormRoutingError("Ответ маршрутизатора содержит данные, похожие на секрет")

    candidates = tuple(sorted(
        (
            RoutingCandidate(
                form_id=str(item["form_id"]),
                score=int(item["score"]),
                reason=str(item["reason"]).strip(),
            )
            for item in payload["candidates"]
        ),
        key=lambda item: (-item.score, item.form_id),
    ))
    if len({candidate.form_id for candidate in candidates}) != len(candidates):
        raise FormRoutingError("Маршрутизатор вернул повторяющиеся формы")
    if not str(payload["reason"]).strip() or any(
        not candidate.reason for candidate in candidates
    ):
        raise FormRoutingError("Маршрутизатор вернул пустое обоснование")

    requested = payload.get("selected_form_id")
    decision = payload["decision"]
    confidence = str(payload["confidence"])
    top = candidates[0]
    second_score = candidates[1].score if len(candidates) > 1 else 0
    can_auto_select = (
        decision == "selected"
        and requested == top.form_id
        and confidence == "high"
        and top.score >= AUTO_SELECT_MIN_SCORE
        and top.score - second_score >= AUTO_SELECT_MIN_MARGIN
    )
    selected = top.form_id if can_auto_select else None
    question = str(payload.get("question") or "").strip()
    if selected is None and not question:
        question = "Какую из предложенных форм использовать?"
    return RoutingDecision(
        selected_form_id=selected,
        confidence=confidence,
        reason=str(payload["reason"]).strip(),
        candidates=candidates,
        question=question,
    )


class FormRouter:
    """Одна заявка → одна изолированная structured-output session выбора формы."""

    def __init__(
        self,
        client: OpenCodeClient,
        itsm_service: ITSMDataSource,
        tfs_service: AzureDevOpsDataSource,
        *,
        forms: Iterable[BaseForm],
        max_context_chars: int = 120_000,
    ) -> None:
        self._client = client
        self._context_builder = ContextBuilder(
            itsm_service,
            tfs_service,
            max_context_chars=max_context_chars,
        )
        self._forms = tuple(forms)
        self._catalog = build_form_catalog(self._forms)
        self._form_ids = tuple(item["form_id"] for item in self._catalog)
        if not self._form_ids:
            raise FormRoutingError("В приложении нет зарегистрированных форм")
        self._session_id: Optional[str] = None
        self._cancel_event: Optional[threading.Event] = None
        self._lock = threading.Lock()

    @property
    def session_id(self) -> Optional[str]:
        with self._lock:
            return self._session_id

    def route(
        self,
        *,
        ticket_id: str,
        environment: str,
        provider_id: str = "",
        model_id: str = "",
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_session: Optional[Callable[[Optional[str]], None]] = None,
    ) -> RoutingOutcome:
        notify = on_progress or (lambda _message: None)
        session_changed = on_session or (lambda _session: None)
        self._cancel_event = cancel_event
        started = time.monotonic()
        try:
            try:
                context = self._context_builder.build(
                    ticket_id=ticket_id,
                    environment=environment,
                    cancel_event=cancel_event,
                    on_progress=notify,
                )
            except InterruptedError as exc:
                raise OpenCodeCancelled("Операция отменена пользователем") from exc
            self._check_cancel()
            timeout = min(10.0, max(0.5, self._client.timeout))
            notify("Проверяю AI-маршрутизатор…")
            self._client.require_agent(FORM_ROUTER_AGENT, timeout=timeout)
            self._client.require_provider(provider_id, timeout=timeout)
            self._check_cancel()

            session_id = self._client.create_session(
                f"AutoDeploy form routing: {context.ticket_id}",
                agent=FORM_ROUTER_AGENT,
                provider_id=provider_id,
                model_id=model_id,
                mcp_names=(),
                metadata={
                    "source": "gravitee-autodeploy-ui-router",
                    "ticket_id": re.sub(r"[\x00-\x1f\x7f]+", "_", context.ticket_id)[:200],
                },
            )
            with self._lock:
                self._session_id = session_id
            session_changed(session_id)
            notify("Определяю подходящую форму…")
            structured = self._client.send_structured_message(
                session_id=session_id,
                prompt=build_routing_prompt(
                    form_catalog=self._catalog,
                    itsm_data=context.itsm,
                    ado_data=context.ado,
                    context_warnings=context.warnings,
                ),
                system=ROUTER_SYSTEM_RULES,
                schema=build_routing_schema(self._form_ids),
                agent=FORM_ROUTER_AGENT,
                provider_id=provider_id,
                model_id=model_id,
                retry_count=2,
                cancel_event=cancel_event,
            )
            notify("Проверяю выбор формы…")
            decision = validate_routing_output(structured, form_ids=self._form_ids)
            _log.info(
                "routing success ticket=%s session=%s selected=%s candidates=%s duration=%.2fs",
                re.sub(r"[\x00-\x1f\x7f]+", "_", context.ticket_id)[:200],
                session_id,
                decision.selected_form_id or "manual-choice",
                ",".join(f"{item.form_id}:{item.score}" for item in decision.candidates),
                time.monotonic() - started,
            )
            return RoutingOutcome(context=context, decision=decision)
        finally:
            self.close(on_session=session_changed)

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        session_id = self.session_id
        if session_id:
            try:
                self._client.abort_session(session_id)
            except Exception:
                _log.warning("routing session abort failed id=%s", session_id, exc_info=True)

    def close(
        self,
        *,
        on_session: Optional[Callable[[Optional[str]], None]] = None,
    ) -> None:
        with self._lock:
            session_id = self._session_id
            self._session_id = None
        if session_id:
            try:
                self._client.delete_session(session_id)
            except Exception:
                _log.warning("routing session delete failed id=%s", session_id, exc_info=True)
        if on_session is not None:
            on_session(None)

    def _check_cancel(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
