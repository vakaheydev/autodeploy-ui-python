"""Единая read-only точка входа: формы, планы, поиск и диагностика."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from config.form_routing import build_form_catalog
from config.mcp_profiles import (
    JSON_REPOSITORY_READ_TOOLS,
    choose_repository_mcp,
    repository_tool_allowlist,
    repository_tool_asklist,
)
from forms.base_form import BaseForm
from opencode_integration.agent import ConversationEvent
from opencode_integration.client import OpenCodeCancelled, OpenCodeClient, OpenCodeError
from opencode_integration.context_builder import (
    BuiltContext,
    ContextBuilder,
    contains_secret,
    redact_text,
    sanitize,
)
from opencode_integration.data_sources import AzureDevOpsDataSource, ITSMDataSource
from opencode_integration.manager import AUTODEPLOY_COPILOT_AGENT
from opencode_integration.prompts import (
    COPILOT_SYSTEM_RULES,
    build_copilot_conversation_prompt,
    build_copilot_prompt,
)
from opencode_integration.schemas import build_copilot_schema
from opencode_integration.workflow import PlannedFormStep

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover - окружение пользователя
    jsonschema = None  # type: ignore[assignment]
    _JSONSCHEMA_IMPORT_ERROR = exc
else:
    _JSONSCHEMA_IMPORT_ERROR = None


_log = logging.getLogger("opencode.copilot")
_FULL_TICKET_RE = re.compile(
    r"^(?:[A-Za-zА-Яа-я][A-Za-zА-Яа-я0-9_]{0,19}[-_/]\d[A-Za-zА-Яа-я0-9_-]{0,39}|\d{3,30})$"
)
_TICKET_IN_TEXT_RE = re.compile(
    r"(?<![\w])((?:"
    r"[A-Za-zА-Яа-я][A-Za-zА-Яа-я0-9_]{0,19}[-_/]\d[A-Za-zА-Яа-я0-9_-]{0,39}"
    r"|\d{3,30}"
    r"))(?![\w])"
)
_TICKET_WORD_RE = re.compile(r"(?i)\b(?:заявк\w*|тикет\w*|ticket|request)\b")
_CASUAL_MESSAGE_RE = re.compile(
    r"(?ix)^\s*(?:"
    r"(?:привет(?:ик)?|здравствуй(?:те)?|hello|hi|hey|"
    r"добр(?:ое\s+утро|ый\s+день|ый\s+вечер))"
    r"(?:\s*[,!?.-]*\s*(?:как\s+дела|what(?:'s|\s+is)\s+up)?)?"
    r"|как\s+дела|кто\s+ты|что\s+ты\s+умеешь|"
    r"спасибо|благодарю|thanks|thank\s+you"
    r")\s*[!?.]*\s*$"
)


class CopilotValidationError(ValueError):
    """Structured response нельзя показывать как проверенный результат."""


@dataclass(frozen=True)
class CopilotFormCandidate:
    form_id: str
    score: int
    reason: str


@dataclass(frozen=True)
class RepositoryItem:
    entity_type: str
    identifier: Optional[str]
    name: Optional[str]
    scope: str
    path: str
    score: int
    reason: str


@dataclass(frozen=True)
class DiagnosticReport:
    summary: str
    probable_causes: tuple[str, ...]
    evidence: tuple[str, ...]
    next_actions: tuple[str, ...]


@dataclass(frozen=True)
class CopilotOutcome:
    intent: str
    answer: str
    question: Optional[str]
    selected_form_id: Optional[str]
    form_candidates: tuple[CopilotFormCandidate, ...]
    plan: tuple[PlannedFormStep, ...]
    repository_items: tuple[RepositoryItem, ...]
    diagnostics: Optional[DiagnosticReport]
    warnings: tuple[str, ...]
    context: Optional[BuiltContext] = None


def detect_ticket_reference(message: str) -> Optional[str]:
    """Консервативно находит ITSM ID, не принимая имя API за заявку."""
    text = str(message).strip()
    if _FULL_TICKET_RE.fullmatch(text):
        return text
    if not _TICKET_WORD_RE.search(text):
        return None
    matches = list(dict.fromkeys(match.group(1) for match in _TICKET_IN_TEXT_RE.finditer(text)))
    return matches[0] if len(matches) == 1 else None


def is_casual_conversation(message: str) -> bool:
    """Распознаёт только безопасный узкий набор small-talk без workflow."""
    return _CASUAL_MESSAGE_RE.fullmatch(str(message)) is not None


def _schema_errors(payload: Any, schema: Mapping[str, Any]) -> list[str]:
    if jsonschema is None:
        raise RuntimeError(
            "Для единого AI-чата требуется пакет jsonschema"
        ) from _JSONSCHEMA_IMPORT_ERROR
    validator_cls = getattr(
        jsonschema,
        "Draft202012Validator",
        jsonschema.Draft7Validator,
    )
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    ]


def validate_copilot_output(
    payload: Any,
    *,
    form_ids: Sequence[str],
    context: Optional[BuiltContext] = None,
) -> CopilotOutcome:
    """Schema + доменные инварианты для ответа главного помощника."""
    schema = build_copilot_schema(form_ids)
    errors = _schema_errors(payload, schema)
    if errors:
        raise CopilotValidationError("Некорректный ответ помощника:\n" + "\n".join(errors))
    if contains_secret(payload):
        raise CopilotValidationError("Ответ помощника содержит данные, похожие на секрет")

    candidates = tuple(
        CopilotFormCandidate(
            form_id=str(item["form_id"]),
            score=int(item["score"]),
            reason=str(item["reason"]).strip(),
        )
        for item in payload["form_candidates"]
    )
    if len({item.form_id for item in candidates}) != len(candidates):
        raise CopilotValidationError("Кандидаты форм должны быть уникальны")
    if tuple(item.score for item in candidates) != tuple(
        sorted((item.score for item in candidates), reverse=True)
    ):
        raise CopilotValidationError("Кандидаты форм должны идти по убыванию score")

    requested = payload.get("selected_form_id")
    selected: Optional[str] = None
    if requested is not None:
        if not candidates or candidates[0].form_id != requested:
            raise CopilotValidationError("Выбранная форма должна быть первым кандидатом")
        second = candidates[1].score if len(candidates) > 1 else 0
        if candidates[0].score >= 80 and candidates[0].score - second >= 15:
            selected = str(requested)

    raw_steps = payload["plan"]
    steps = tuple(
        PlannedFormStep(
            step_id=str(item["step_id"]),
            position=int(item["position"]),
            form_id=str(item["form_id"]),
            title=str(item["title"]).strip(),
            reason=str(item["reason"]).strip(),
            depends_on=tuple(str(value) for value in item["depends_on"]),
            confidence=str(item["confidence"]),
        )
        for item in raw_steps
    )
    step_ids = [item.step_id for item in steps]
    if len(step_ids) != len(set(step_ids)):
        raise CopilotValidationError("step_id в плане должны быть уникальны")
    if [item.position for item in steps] != list(range(1, len(steps) + 1)):
        raise CopilotValidationError("Позиции шагов плана должны быть последовательными с 1")
    positions = {item.step_id: item.position for item in steps}
    for item in steps:
        unknown = [dep for dep in item.depends_on if dep not in positions]
        late = [dep for dep in item.depends_on if positions.get(dep, 10_000) >= item.position]
        if unknown:
            raise CopilotValidationError(
                f"Шаг {item.step_id} зависит от неизвестных шагов: {', '.join(unknown)}"
            )
        if late:
            raise CopilotValidationError(
                f"Шаг {item.step_id} может зависеть только от предыдущих шагов"
            )

    items = tuple(
        RepositoryItem(
            entity_type=str(item["entity_type"]),
            identifier=(str(item["identifier"]) if item["identifier"] is not None else None),
            name=(str(item["name"]) if item["name"] is not None else None),
            scope=str(item["scope"]),
            path=str(item["path"]),
            score=int(item["score"]),
            reason=str(item["reason"]).strip(),
        )
        for item in payload["repository_items"]
    )
    repository_keys = [(item.scope, item.path) for item in items]
    if len(repository_keys) != len(set(repository_keys)):
        raise CopilotValidationError("Репозиторные результаты должны быть уникальны")
    if tuple(item.score for item in items) != tuple(
        sorted((item.score for item in items), reverse=True)
    ):
        raise CopilotValidationError(
            "Репозиторные результаты должны идти по убыванию score"
        )
    raw_diagnostics = payload["diagnostics"]
    diagnostics = (
        DiagnosticReport(
            summary=str(raw_diagnostics["summary"]).strip(),
            probable_causes=tuple(str(item) for item in raw_diagnostics["probable_causes"]),
            evidence=tuple(str(item) for item in raw_diagnostics["evidence"]),
            next_actions=tuple(str(item) for item in raw_diagnostics["next_actions"]),
        )
        if raw_diagnostics is not None
        else None
    )

    intent = str(payload["intent"])
    question = str(payload["question"]).strip() if payload["question"] is not None else None
    if intent == "single_form" and not candidates:
        raise CopilotValidationError("Для single_form нужен хотя бы один кандидат")
    expected_candidates = min(3, len(tuple(dict.fromkeys(form_ids))))
    if intent == "single_form" and len(candidates) != expected_candidates:
        raise CopilotValidationError(
            f"Для single_form нужны ровно {expected_candidates} лучших кандидата"
        )
    if intent == "single_form" and selected is None and not question:
        raise CopilotValidationError("Неоднозначный выбор формы требует вопроса пользователю")
    if intent != "single_form" and (candidates or requested is not None):
        raise CopilotValidationError(
            "Кандидаты и выбранная форма допустимы только для single_form"
        )
    if intent == "execution_plan" and len(steps) < 2:
        raise CopilotValidationError("Многошаговый план должен содержать минимум два шага")
    if intent != "execution_plan" and steps:
        raise CopilotValidationError("Шаги допустимы только для execution_plan")
    if intent != "diagnostics" and diagnostics is not None:
        raise CopilotValidationError(
            "Диагностический отчёт допустим только для diagnostics"
        )
    if intent == "diagnostics" and diagnostics is None:
        raise CopilotValidationError("Для diagnostics требуется диагностический отчёт")
    if intent == "clarification" and not question:
        raise CopilotValidationError("Для clarification требуется вопрос")

    return CopilotOutcome(
        intent=intent,
        answer=str(payload["answer"]).strip(),
        question=question,
        selected_form_id=selected,
        form_candidates=candidates,
        plan=steps,
        repository_items=items,
        diagnostics=diagnostics,
        warnings=tuple(dict.fromkeys(str(item) for item in payload["warnings"])),
        context=context,
    )


class UnifiedCopilot:
    """Долгоживущая OpenCode session в пределах одного главного экрана."""

    def __init__(
        self,
        client: OpenCodeClient,
        itsm_service: ITSMDataSource,
        tfs_service: AzureDevOpsDataSource,
        *,
        forms: Iterable[BaseForm],
        allowed_mcp: Sequence[str] = (),
        repository_mcp: str = "",
        allow_repository_git_pull: bool = True,
        max_context_chars: int = 120_000,
    ) -> None:
        self._client = client
        self._context_builder = ContextBuilder(
            itsm_service, tfs_service, max_context_chars=max_context_chars
        )
        self._forms = tuple(forms)
        self._catalog = build_form_catalog(self._forms)
        self._form_ids = tuple(item["form_id"] for item in self._catalog)
        self._allowed_mcp = tuple(allowed_mcp)
        self._configured_repository_mcp = repository_mcp.strip()
        self._allow_repository_git_pull = bool(allow_repository_git_pull)
        self._max_context_chars = max(10_000, min(500_000, int(max_context_chars)))
        self._active_repository_mcp = ""
        self._active_mcp: tuple[str, ...] = ()
        self._session_id: Optional[str] = None
        self._context: Optional[BuiltContext] = None
        self._cancel_event: Optional[threading.Event] = None
        self._provider_id = ""
        self._model_id = ""
        self._on_event: Callable[[ConversationEvent], None] = lambda _event: None
        self._on_session: Callable[[Optional[str]], None] = lambda _session: None
        self._part_states: dict[str, str] = {}
        self._permission_ids: set[str] = set()
        self._last_session_status_signature = ""
        self._event_lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._repository_evidence: set[tuple[str, str]] = set()

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def context(self) -> Optional[BuiltContext]:
        return self._context

    @property
    def repository_mcp(self) -> str:
        return self._active_repository_mcp

    def ask(
        self,
        message: str,
        *,
        environment: str,
        ticket_id: Optional[str] = None,
        diagnostic_data: Any = None,
        provider_id: str = "",
        model_id: str = "",
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[ConversationEvent], None]] = None,
        on_session: Optional[Callable[[Optional[str]], None]] = None,
    ) -> CopilotOutcome:
        with self._operation_lock:
            text = redact_text(str(message).strip())
            if not text:
                raise ValueError("Введите сообщение для AI-помощника")
            if len(text) > 20_000:
                raise ValueError("Сообщение превышает 20000 символов")
            notify = on_progress or (lambda _message: None)
            self._cancel_event = cancel_event
            self._on_event = on_event or (lambda _event: None)
            self._on_session = on_session or (lambda _session: None)
            self._provider_id = provider_id
            self._model_id = model_id
            self._last_session_status_signature = ""
            started = time.monotonic()

            requested_ticket = ticket_id or detect_ticket_reference(text)
            if requested_ticket and (
                self._context is None or self._context.ticket_id != requested_ticket
            ):
                try:
                    new_context = self._context_builder.build(
                        ticket_id=requested_ticket,
                        environment=environment,
                        cancel_event=cancel_event,
                        on_progress=notify,
                    )
                except InterruptedError as exc:
                    raise OpenCodeCancelled("Операция отменена пользователем") from exc
                # Другая заявка никогда не продолжает старую conversation:
                # контекст и MCP evidence из разных заявок не смешиваются.
                if self._context is not None:
                    notify("Создаю отдельную AI-сессию для новой заявки…")
                    self._reset_session()
                self._context = new_context
            self._check_cancel()
            self._ensure_session(notify)
            context = self._context

            if diagnostic_data is None and is_casual_conversation(text):
                notify("OpenCode готовит ответ…")
                message_result = self._client.send_chat_message(
                    session_id=self._require_session(),
                    prompt=build_copilot_conversation_prompt(text),
                    system=COPILOT_SYSTEM_RULES,
                    agent=AUTODEPLOY_COPILOT_AGENT,
                    provider_id=provider_id,
                    model_id=model_id,
                    cancel_event=cancel_event,
                    on_event=self._handle_raw_event,
                    on_response=self._capture_response_evidence,
                )
                answer = message_result.text.strip()
                if not answer:
                    raise OpenCodeError("OpenCode вернул пустой ответ")
                if contains_secret(answer):
                    raise CopilotValidationError(
                        "Ответ помощника содержит данные, похожие на секрет"
                    )
                outcome = CopilotOutcome(
                    intent="conversation",
                    answer=answer,
                    question=None,
                    selected_form_id=None,
                    form_candidates=(),
                    plan=(),
                    repository_items=(),
                    diagnostics=None,
                    warnings=(),
                    context=context,
                )
                _log.info(
                    "copilot conversation success session=%s duration=%.2fs",
                    self._session_id,
                    time.monotonic() - started,
                )
                return outcome

            notify("AI анализирует запрос и при необходимости ищет в репозитории…")
            structured = self._client.send_structured_message(
                session_id=self._require_session(),
                prompt=build_copilot_prompt(
                    operator_message=text,
                    environment=environment,
                    form_catalog=self._catalog,
                    repository_mcp=self._active_repository_mcp,
                    other_mcp=tuple(
                        name
                        for name in self._active_mcp
                        if name != self._active_repository_mcp
                    ),
                    itsm_data=context.itsm if context else None,
                    ado_data=context.ado if context else None,
                    context_warnings=context.warnings if context else (),
                    diagnostic_data=self._bounded_diagnostic_data(diagnostic_data),
                    allow_repository_git_pull=self._allow_repository_git_pull,
                ),
                system=COPILOT_SYSTEM_RULES,
                schema=build_copilot_schema(self._form_ids),
                agent=AUTODEPLOY_COPILOT_AGENT,
                provider_id=provider_id,
                model_id=model_id,
                retry_count=2,
                cancel_event=cancel_event,
                on_event=self._handle_raw_event,
                on_response=self._capture_response_evidence,
            )
            notify("Проверяю ответ помощника Python-валидатором…")
            outcome = validate_copilot_output(
                structured,
                form_ids=self._form_ids,
                context=context,
            )
            self._verify_repository_evidence(outcome)
            _log.info(
                "copilot success session=%s intent=%s ticket=%s repository_items=%d "
                "plan_steps=%d duration=%.2fs",
                self._session_id,
                outcome.intent,
                context.ticket_id if context else "none",
                len(outcome.repository_items),
                len(outcome.plan),
                time.monotonic() - started,
            )
            return outcome

    def _ensure_session(self, notify: Callable[[str], None]) -> None:
        if self._session_id is not None:
            return
        timeout = min(10.0, max(0.5, self._client.timeout))
        notify("Проверяю единого AI-помощника и provider…")
        self._client.require_agent(AUTODEPLOY_COPILOT_AGENT, timeout=timeout)
        self._client.require_provider(self._provider_id, timeout=timeout)
        statuses = self._client.list_mcp_servers(timeout=timeout)
        self._active_repository_mcp = choose_repository_mcp(
            self._configured_repository_mcp,
            self._allowed_mcp,
            statuses,
        )
        if self._configured_repository_mcp and not self._active_repository_mcp:
            self._emit(ConversationEvent(
                "warning",
                "JSON Repository MCP недоступен",
                f"Сервер {self._configured_repository_mcp!r} не подключён; "
                "поиск по репозиторию для этой сессии отключён.",
            ))
        mcp_names = [
            name
            for name in dict.fromkeys(self._allowed_mcp)
            if statuses.get(name, {}).get("status") == "connected"
        ]
        if self._active_repository_mcp and self._active_repository_mcp not in mcp_names:
            mcp_names.append(self._active_repository_mcp)
        self._active_mcp = tuple(mcp_names)
        self._session_id = self._client.create_session(
            "Gravitee AutoDeploy unified copilot",
            agent=AUTODEPLOY_COPILOT_AGENT,
            provider_id=self._provider_id,
            model_id=self._model_id,
            mcp_names=mcp_names,
            mcp_tool_allowlist=repository_tool_allowlist(self._active_repository_mcp),
            mcp_tool_asklist=repository_tool_asklist(
                self._active_repository_mcp,
                allow_git_pull=self._allow_repository_git_pull,
            ),
            metadata={"source": "gravitee-autodeploy-ui-copilot"},
        )
        self._on_session(self._session_id)
        self._emit(ConversationEvent(
            "system",
            "Сессия единого помощника создана",
            f"JSON Repository MCP: {self._active_repository_mcp or 'не подключён'}; "
            "git_pull: "
            + ("спросить каждый раз" if self._allow_repository_git_pull else "запрещён")
            + "; прочие MCP: "
            + (
                ", ".join(
                    name
                    for name in mcp_names
                    if name != self._active_repository_mcp
                )
                or "нет"
            ),
        ))

    def approve_permission(self, permission_id: str, *, allow: bool) -> None:
        self._client.respond_permission(
            self._require_session(), permission_id, "once" if allow else "reject"
        )

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._session_id is not None:
            try:
                self._client.abort_session(self._session_id)
            except Exception:
                _log.warning("copilot session abort failed id=%s", self._session_id, exc_info=True)

    def close(self) -> None:
        self._reset_session()

    def _reset_session(self) -> None:
        """Удаляет session и очищает всё накопленное внешнее evidence."""
        session_id = self._session_id
        self._session_id = None
        if session_id is not None:
            try:
                self._client.delete_session(session_id)
            except Exception:
                _log.warning("copilot session delete failed id=%s", session_id, exc_info=True)
        self._active_repository_mcp = ""
        self._active_mcp = ()
        self._repository_evidence.clear()
        self._part_states.clear()
        self._permission_ids.clear()
        self._last_session_status_signature = ""
        self._on_session(None)

    def _handle_raw_event(self, event: Mapping[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        props = event.get("properties")
        values = props if isinstance(props, dict) else {}
        if event_type == "client.sse.disconnected":
            self._emit(ConversationEvent("warning", "Поток событий переподключается"))
            return
        if event_type in {"permission.asked", "permission.updated"}:
            permission_id = str(values.get("id") or values.get("permissionID") or "")
            if permission_id:
                with self._event_lock:
                    if permission_id in self._permission_ids:
                        return
                    self._permission_ids.add(permission_id)
            permission_name = str(values.get("permission") or values.get("tool") or "MCP tool")
            self._emit(ConversationEvent(
                "permission",
                f"Требуется разрешение: {permission_name}",
                self._safe_detail(values.get("metadata", values.get("patterns", []))),
                permission_id=permission_id,
                permission_name=permission_name,
            ))
            return
        if event_type == "session.status":
            status = values.get("status")
            if isinstance(status, dict):
                status_type = str(status.get("type") or "unknown")
                attempt = status.get("attempt")
                next_at = status.get("next")
                signature = json.dumps(
                    [status_type, attempt, next_at],
                    ensure_ascii=False,
                    default=str,
                    separators=(",", ":"),
                )
                with self._event_lock:
                    if signature == self._last_session_status_signature:
                        return
                    self._last_session_status_signature = signature
                labels = {
                    "busy": "OpenCode анализирует запрос",
                    "retry": "OpenCode повторяет запрос",
                    "idle": "OpenCode завершает обработку",
                }
                detail = f"попытка {attempt}" if attempt not in (None, "") else ""
                self._emit(ConversationEvent(
                    "status",
                    labels.get(status_type, f"OpenCode: {status_type}"),
                    detail,
                ))
            return
        if event_type in {"session.error", "session.failed"}:
            self._emit(ConversationEvent(
                "error", "Ошибка OpenCode session", self._safe_detail(values.get("error", values))
            ))
            return
        if event_type == "message.part.updated":
            part = values.get("part")
            if not isinstance(part, dict) or part.get("type") != "tool":
                return
            part_id = str(part.get("id") or part.get("callID") or "")
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = str(state.get("status") or "updated")
            if part_id and self._part_states.get(part_id) == status:
                return
            if part_id:
                self._part_states[part_id] = status
            tool = str(part.get("tool") or state.get("title") or "MCP tool")
            detail = state.get("error") if status == "error" else state.get("input", "")
            if (
                status != "error"
                and "output" in state
                and self._is_repository_read_tool(tool)
            ):
                self._record_repository_evidence(state.get("output"))
            self._emit(ConversationEvent(
                "error" if status == "error" else "tool",
                f"{tool}: {status}",
                self._safe_detail(detail),
            ))

    def _capture_response_evidence(self, response: Mapping[str, Any]) -> None:
        parts = response.get("parts", ())
        if not isinstance(parts, (list, tuple)):
            return
        for part in parts:
            if not isinstance(part, Mapping) or part.get("type") != "tool":
                continue
            tool = str(part.get("tool") or "")
            if not self._is_repository_read_tool(tool):
                continue
            state = part.get("state")
            if isinstance(state, Mapping):
                self._record_repository_evidence(state.get("output"))

    def _is_repository_read_tool(self, tool: str) -> bool:
        server = self._active_repository_mcp
        if not server:
            return False
        return tool in {
            f"{server}_{tool_name}" for tool_name in JSON_REPOSITORY_READ_TOOLS
        }

    def _bounded_diagnostic_data(self, value: Any) -> Any:
        """Очищает диагностический payload и жёстко ограничивает его размер."""
        clean = sanitize(value)
        if clean is None:
            return None
        budget = min(60_000, max(5_000, self._max_context_chars // 2))
        rendered = json.dumps(
            clean,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        if len(rendered) <= budget:
            return clean
        return {
            "_truncated": True,
            "_original_characters": len(rendered),
            "_json_excerpt": rendered[: max(0, budget - 120)],
        }

    def _record_repository_evidence(self, value: Any) -> None:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return
            self._record_repository_evidence(decoded)
            return
        if isinstance(value, Mapping):
            path = value.get("x-filepath")
            scope = value.get("scope")
            if isinstance(path, str) and isinstance(scope, str):
                self._repository_evidence.add((scope, path))
            for child in value.values():
                self._record_repository_evidence(child)
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                self._record_repository_evidence(child)

    def _verify_repository_evidence(self, outcome: CopilotOutcome) -> None:
        unsupported = [
            f"{item.scope}:{item.path}"
            for item in outcome.repository_items
            if (item.scope, item.path) not in self._repository_evidence
        ]
        if unsupported:
            raise CopilotValidationError(
                "Ответ содержит репозиторные источники, которых не было в "
                "подтверждённых MCP-результатах: " + ", ".join(unsupported[:10])
            )

    @staticmethod
    def _safe_detail(value: Any) -> str:
        try:
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            rendered = str(value)
        return redact_text(rendered)[:2000]

    def _emit(self, event: ConversationEvent) -> None:
        if event.kind == "status":
            _log.info(
                "copilot event kind=status title=%s detail=%s",
                event.title,
                event.detail or "none",
            )
        else:
            _log.info("copilot event kind=%s title=%s", event.kind, event.title)
        self._on_event(event)

    def _require_session(self) -> str:
        if self._session_id is None:
            raise RuntimeError("OpenCode copilot session не создана")
        return self._session_id

    def _check_cancel(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
