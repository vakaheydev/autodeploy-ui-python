"""Единая read-only точка входа: формы, планы, поиск и диагностика."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from config.form_routing import build_form_catalog
from config.mcp_profiles import (
    AUTODEPLOY_MCP_NAME,
    choose_repository_mcp,
    repository_tool_allowlist,
    repository_tool_asklist,
)
from forms.base_form import BaseForm
from opencode_integration.agent import ConversationEvent
from opencode_integration.client import (
    OpenCodeCancelled,
    OpenCodeClient,
    OpenCodeError,
    opencode_context_tokens,
    opencode_message_duration,
    opencode_text_generation_duration,
)
from opencode_integration.context_builder import (
    BuiltContext,
    ContextBuilder,
    redact_text,
    sanitize,
)
from opencode_integration.data_sources import AzureDevOpsDataSource, ITSMDataSource
from opencode_integration.manager import AUTODEPLOY_COPILOT_AGENT
from opencode_integration.prompts import (
    COPILOT_SYSTEM_RULES,
    MCP_COPILOT_SYSTEM_RULES,
    build_copilot_conversation_prompt,
    build_copilot_environment_context,
    build_mcp_copilot_prompt,
    build_mcp_copilot_session_context,
    build_copilot_prompt,
    build_copilot_session_context,
    build_copilot_ticket_context,
)
from opencode_integration.schemas import build_copilot_schema
from opencode_integration.workflow import (
    AIFieldProposal,
    ExtractionDirective,
    PlannedFormStep,
)

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
_HIDDEN_REASONING_BLOCK_RE = re.compile(
    r"(?is)<(?:think|reasoning)>.*?</(?:think|reasoning)>"
)
_OPEN_REASONING_TAIL_RE = re.compile(r"(?is)<(?:think|reasoning)>.*$")


def _assistant_text_part_allowed(part: Mapping[str, Any]) -> bool:
    if (
        part.get("type") != "text"
        or part.get("ignored") is True
        or part.get("synthetic") is True
    ):
        return False
    metadata = part.get("metadata")
    if isinstance(metadata, Mapping):
        channel = str(
            metadata.get("channel")
            or metadata.get("type")
            or metadata.get("kind")
            or ""
        ).casefold()
        if channel in {"analysis", "reasoning", "thinking", "thought"}:
            return False
    return True


def visible_assistant_text(part: Mapping[str, Any]) -> str:
    """Return displayable model narration, never OpenCode reasoning parts."""
    if not _assistant_text_part_allowed(part):
        return ""
    text = str(part.get("text") or "")
    text = _HIDDEN_REASONING_BLOCK_RE.sub("", text)
    text = _OPEN_REASONING_TAIL_RE.sub("", text)
    return text.strip()


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
    extraction: Optional[ExtractionDirective]
    plan: tuple[PlannedFormStep, ...]
    repository_items: tuple[RepositoryItem, ...]
    diagnostics: Optional[DiagnosticReport]
    warnings: tuple[str, ...]
    context: Optional[BuiltContext] = None
    elapsed_seconds: float = 0.0
    opencode_seconds: Optional[float] = None
    generation_seconds: Optional[float] = None
    tokens_used: int = 0


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
    forms: Iterable[BaseForm] = (),
    context: Optional[BuiltContext] = None,
) -> CopilotOutcome:
    """Schema + доменные инварианты для ответа главного помощника."""
    schema = build_copilot_schema(form_ids)
    errors = _schema_errors(payload, schema)
    if errors:
        raise CopilotValidationError("Некорректный ответ помощника:\n" + "\n".join(errors))
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

    form_map = {form.form_id: form for form in forms}

    def parse_extraction(raw: Mapping[str, Any]) -> ExtractionDirective:
        proposals = tuple(
            AIFieldProposal(
                field_key=str(item["field_key"]),
                value=item["value"],
                source=str(item["source"]).strip(),
                confidence=str(item["confidence"]),
            )
            for item in raw["field_proposals"]
        )
        directive = ExtractionDirective(
            form_id=str(raw["form_id"]),
            mode=str(raw["mode"]),
            field_proposals=proposals,
            missing_information=tuple(
                str(item).strip() for item in raw["missing_information"]
            ),
            research_goal=(
                str(raw["research_goal"]).strip()
                if raw["research_goal"] is not None
                else ""
            ),
        )
        keys = [item.field_key for item in proposals]
        if len(keys) != len(set(keys)):
            raise CopilotValidationError(
                f"Подсказки полей для {directive.form_id} должны быть уникальны"
            )
        if directive.mode == "fill_only":
            if directive.missing_information or directive.research_goal:
                raise CopilotValidationError(
                    "fill_only не может содержать missing_information или research_goal"
                )
            if any(
                item.confidence not in {"high", "medium"}
                for item in proposals
            ):
                raise CopilotValidationError(
                    "fill_only допускает только high/medium field proposals"
                )
        elif not directive.research_goal:
            raise CopilotValidationError(
                "Для research требуется конкретная цель исследования"
            )

        form = form_map.get(directive.form_id)
        if form is not None:
            fields = {field.key: field for field in form.fields}
            unknown = sorted(set(keys) - set(fields))
            if unknown:
                raise CopilotValidationError(
                    f"Неизвестные поля формы {directive.form_id}: {', '.join(unknown)}"
                )
            # Это промежуточные смысловые подсказки для form-extractor, а не
            # готовые значения формы. Проверять их по финальной field schema
            # преждевременно: extractor ещё нормализует пути, типы и справочные
            # labels/IDs. Строгая schema + domain validation остаётся перед
            # preview и применением результата к форме.
            if directive.mode == "fill_only":
                provided = set(keys)
                missing_required = [
                    field.key
                    for field in form.fields
                    if field.required and field.key not in provided
                ]
                if missing_required:
                    raise CopilotValidationError(
                        "Copilot выбрал fill_only без обязательных полей: "
                        + ", ".join(missing_required)
                    )
        return directive

    raw_extraction = payload["extraction"]
    extraction = (
        parse_extraction(raw_extraction)
        if isinstance(raw_extraction, Mapping)
        else None
    )

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
            extraction=parse_extraction(item["extraction"]),
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
        if item.extraction is None or item.extraction.form_id != item.form_id:
            raise CopilotValidationError(
                f"Extraction directive шага {item.step_id} относится не к его форме"
            )
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
    if intent == "single_form" and requested is not None:
        if extraction is None or extraction.form_id != requested:
            raise CopilotValidationError(
                "Выбранная форма требует соответствующий extraction directive"
            )
    elif intent == "single_form" and extraction is not None:
        raise CopilotValidationError(
            "Extraction directive требует выбранную форму"
        )
    if intent != "single_form":
        # Кандидаты полезны и при clarification: модель может объяснить
        # неоднозначность и показать варианты. Но открыть форму автоматически
        # разрешено только явному intent=single_form.
        selected = None
        extraction = None
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
        extraction=extraction,
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
        trusted_mcp_tools: Optional[Mapping[str, Sequence[str]]] = None,
        trusted_mcp_ask_tools: Optional[Mapping[str, Sequence[str]]] = None,
        workflow_id: str = "",
    ) -> None:
        self._client = client
        self._context_builder = ContextBuilder(
            itsm_service, tfs_service, max_context_chars=max_context_chars
        )
        self._forms = tuple(forms)
        self._workflow_id = str(workflow_id).strip()
        # Legacy desktop callers keep the old structured route until their UI
        # migrates. The web MCP-native route never constructs or stores the
        # catalog in the main Copilot session.
        self._catalog = (
            build_form_catalog(self._forms) if not self._workflow_id else []
        )
        self._form_ids = tuple(item["form_id"] for item in self._catalog)
        self._allowed_mcp = tuple(allowed_mcp)
        self._configured_repository_mcp = repository_mcp.strip()
        self._allow_repository_git_pull = bool(allow_repository_git_pull)
        self._max_context_chars = max(10_000, min(500_000, int(max_context_chars)))
        self._trusted_mcp_tools = {
            str(name): tuple(str(tool) for tool in tools)
            for name, tools in (trusted_mcp_tools or {}).items()
        }
        self._trusted_mcp_ask_tools = {
            str(name): tuple(str(tool) for tool in tools)
            for name, tools in (trusted_mcp_ask_tools or {}).items()
        }
        self._active_repository_mcp = ""
        self._active_mcp: tuple[str, ...] = ()
        self._session_id: Optional[str] = None
        self._context: Optional[BuiltContext] = None
        self._cancel_event: Optional[threading.Event] = None
        self._provider_id = ""
        self._model_id = ""
        self._variant = ""
        self._on_event: Callable[[ConversationEvent], None] = lambda _event: None
        self._on_session: Callable[[Optional[str]], None] = lambda _session: None
        self._part_states: dict[str, str] = {}
        self._part_started_at: dict[str, float] = {}
        self._pending_text_parts: dict[str, tuple[str, str]] = {}
        self._message_roles: dict[str, str] = {}
        self._permission_ids: set[str] = set()
        self._last_session_status_signature = ""
        self._event_lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._session_context_initialized = False
        self._sent_ticket_contexts: set[str] = set()
        self._current_environment = ""

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def context(self) -> Optional[BuiltContext]:
        return self._context

    @property
    def repository_mcp(self) -> str:
        return self._active_repository_mcp

    @property
    def model_selection(self) -> tuple[str, str, str]:
        return self._provider_id, self._model_id, self._variant

    @property
    def server_url(self) -> str:
        return self._client.base_url

    @property
    def mcp_native(self) -> bool:
        return bool(self._workflow_id)

    def resume_session(self, session_id: str) -> None:
        """Attach to a persisted AutoDeploy-owned OpenCode session."""
        clean_id = str(session_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", clean_id):
            raise ValueError("Некорректный OpenCode session ID")
        statuses = self._client.list_mcp_servers(
            timeout=min(10.0, max(0.5, self._client.timeout))
        )
        self._active_repository_mcp = choose_repository_mcp(
            self._configured_repository_mcp,
            self._allowed_mcp,
            statuses,
        )
        self._active_mcp = tuple(
            name for name in dict.fromkeys(self._allowed_mcp)
            if statuses.get(name, {}).get("status") == "connected"
        )
        self._session_id = clean_id
        self._session_context_initialized = True
        self._on_session(clean_id)

    def detach(self) -> None:
        """Forget the local handle while preserving OpenCode's persisted chat."""
        self._session_id = None
        self._active_repository_mcp = ""
        self._active_mcp = ()
        self._session_context_initialized = False
        self._sent_ticket_contexts.clear()
        self._current_environment = ""
        self._part_states.clear()
        self._part_started_at.clear()
        self._pending_text_parts.clear()
        self._message_roles.clear()
        self._permission_ids.clear()
        self._last_session_status_signature = ""
        self._on_session(None)

    def ask(
        self,
        message: str,
        *,
        environment: str,
        ticket_id: Optional[str] = None,
        diagnostic_data: Any = None,
        provider_id: str = "",
        model_id: str = "",
        variant: str = "",
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[ConversationEvent], None]] = None,
        on_session: Optional[Callable[[Optional[str]], None]] = None,
        draft_context: Any = None,
        operator_references: Any = None,
        detect_ticket_references: bool = True,
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
            self._variant = variant
            self._last_session_status_signature = ""
            self._discard_pending_text_parts()
            started = time.monotonic()
            opencode_durations: list[float] = []
            generation_seconds: Optional[float] = None
            context_tokens = 0

            def observe_response(response: Mapping[str, Any]) -> None:
                nonlocal generation_seconds, context_tokens
                info = response.get("info")
                if isinstance(info, Mapping):
                    duration = opencode_message_duration(info)
                    if duration is not None:
                        opencode_durations.append(duration)
                    context_tokens = opencode_context_tokens(info)
                raw_parts = response.get("parts")
                if isinstance(raw_parts, (list, tuple)):
                    generation_seconds = opencode_text_generation_duration(
                        tuple(item for item in raw_parts if isinstance(item, Mapping))
                    )

            requested_ticket = ticket_id or (
                detect_ticket_reference(text) if detect_ticket_references else None
            )
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
                self._context = new_context
            self._check_cancel()
            self._ensure_session(notify)
            context = self._context
            self._ensure_context_stored(
                environment=environment,
                context=context,
                notify=notify,
            )

            if self._workflow_id:
                notify("Copilot анализирует запрос и выбирает нужные инструменты…")
                message_result = self._client.send_chat_message(
                    session_id=self._require_session(),
                    prompt=build_mcp_copilot_prompt(
                        operator_message=text,
                        diagnostic_data=self._bounded_diagnostic_data(diagnostic_data),
                        draft_context=draft_context,
                        operator_references=operator_references,
                    ),
                    system=MCP_COPILOT_SYSTEM_RULES,
                    agent=AUTODEPLOY_COPILOT_AGENT,
                    provider_id=provider_id,
                    model_id=model_id,
                    variant=variant,
                    cancel_event=cancel_event,
                    on_event=self._handle_raw_event,
                )
                answer = visible_assistant_text({
                    "type": "text",
                    "text": message_result.text,
                })
                self._discard_pending_text_parts()
                if not answer:
                    raise OpenCodeError("OpenCode вернул пустой ответ")
                outcome = CopilotOutcome(
                    intent="conversation",
                    answer=answer,
                    question=None,
                    selected_form_id=None,
                    form_candidates=(),
                    extraction=None,
                    plan=(),
                    repository_items=(),
                    diagnostics=None,
                    warnings=(),
                    context=context,
                    elapsed_seconds=time.monotonic() - started,
                    opencode_seconds=opencode_message_duration(message_result.info),
                    generation_seconds=opencode_text_generation_duration(
                        message_result.parts
                    ),
                    tokens_used=opencode_context_tokens(message_result.info),
                )
                _log.info(
                    "mcp-native copilot success session=%s ticket=%s duration=%.2fs",
                    self._session_id,
                    context.ticket_id if context else "none",
                    time.monotonic() - started,
                )
                return outcome

            if diagnostic_data is None and is_casual_conversation(text):
                notify("OpenCode готовит ответ…")
                message_result = self._client.send_chat_message(
                    session_id=self._require_session(),
                    prompt=build_copilot_conversation_prompt(
                        text,
                        operator_references=operator_references,
                    ),
                    system=COPILOT_SYSTEM_RULES,
                    agent=AUTODEPLOY_COPILOT_AGENT,
                    provider_id=provider_id,
                    model_id=model_id,
                    variant=variant,
                    cancel_event=cancel_event,
                    on_event=self._handle_raw_event,
                )
                answer = visible_assistant_text({
                    "type": "text",
                    "text": message_result.text,
                })
                self._discard_pending_text_parts()
                if not answer:
                    raise OpenCodeError("OpenCode вернул пустой ответ")
                outcome = CopilotOutcome(
                    intent="conversation",
                    answer=answer,
                    question=None,
                    selected_form_id=None,
                    form_candidates=(),
                    extraction=None,
                    plan=(),
                    repository_items=(),
                    diagnostics=None,
                    warnings=(),
                    context=context,
                    elapsed_seconds=time.monotonic() - started,
                    opencode_seconds=opencode_message_duration(message_result.info),
                    generation_seconds=opencode_text_generation_duration(
                        message_result.parts
                    ),
                    tokens_used=opencode_context_tokens(message_result.info),
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
                    diagnostic_data=self._bounded_diagnostic_data(diagnostic_data),
                    operator_references=operator_references,
                ),
                system=COPILOT_SYSTEM_RULES,
                schema=build_copilot_schema(self._form_ids),
                agent=AUTODEPLOY_COPILOT_AGENT,
                provider_id=provider_id,
                model_id=model_id,
                variant=variant,
                retry_count=2,
                cancel_event=cancel_event,
                on_event=self._handle_raw_event,
                on_response=observe_response,
            )
            self._discard_pending_text_parts()
            notify("Проверяю ответ помощника Python-валидатором…")
            outcome = validate_copilot_output(
                structured,
                form_ids=self._form_ids,
                forms=self._forms,
                context=context,
            )
            if context is None and (
                outcome.intent in {"single_form", "execution_plan"}
                or bool(outcome.form_candidates)
            ):
                # Запрос из главного чата может не иметь ITSM ID. Для этапа
                # extractor достаточно очищенного текста оператора и уже
                # валидированного handoff. Это также позволяет пользователю
                # выбрать один из кандидатов после clarification без ITSM ID.
                context = BuiltContext(
                    ticket_id="",
                    itsm={
                        "source": "Gravitee Copilot chat",
                        "operator_request": text,
                    },
                    ado=None,
                    # Отсутствие ITSM ID в главном чате — штатный
                    # сценарий, а не warning для preview.
                    warnings=[],
                )
                outcome = replace(outcome, context=context)
            outcome = replace(
                outcome,
                elapsed_seconds=time.monotonic() - started,
                opencode_seconds=(sum(opencode_durations) if opencode_durations else None),
                generation_seconds=generation_seconds,
                tokens_used=context_tokens,
            )
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
        unavailable_trusted = [
            name
            for name in set(self._trusted_mcp_tools) | set(self._trusted_mcp_ask_tools)
            if statuses.get(name, {}).get("status") != "connected"
        ]
        if unavailable_trusted:
            raise OpenCodeError(
                "Встроенный AutoDeploy MCP включён, но OpenCode не подключил "
                "сервер: " + ", ".join(unavailable_trusted)
                + ". Проверьте /api/mcp, переподключите OpenCode и создайте новый чат."
            )
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
        allowlist = repository_tool_allowlist(self._active_repository_mcp)
        allowlist.update({
            name: tools for name, tools in self._trusted_mcp_tools.items()
            if name in mcp_names
        })
        # Omitting a title lets OpenCode generate its own concise session name
        # from the first real operator turn.  AutoDeploy reads that title back
        # and still allows the operator to override it explicitly.
        asklist = repository_tool_asklist(
            self._active_repository_mcp,
            allow_git_pull=self._allow_repository_git_pull,
        )
        asklist.update({
            name: tools for name, tools in self._trusted_mcp_ask_tools.items()
            if name in mcp_names
        })
        self._session_id = self._client.create_session(
            "",
            agent=AUTODEPLOY_COPILOT_AGENT,
            provider_id=self._provider_id,
            model_id=self._model_id,
            variant=self._variant,
            mcp_names=mcp_names,
            mcp_tool_allowlist=allowlist,
            mcp_tool_asklist=asklist,
            metadata={
                "source": "gravitee-autodeploy-ui-copilot",
                "workflow_id": self._workflow_id,
            },
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

    def _ensure_context_stored(
        self,
        *,
        environment: str,
        context: Optional[BuiltContext],
        notify: Callable[[str], None],
    ) -> None:
        """Stores stable context once; MCP-native web mode excludes the catalog."""
        ticket_id = context.ticket_id if context is not None else ""
        if not self._session_context_initialized:
            notify("Один раз сохраняю контекст в истории AI-сессии…")
            common = {
                "environment": environment,
                "repository_mcp": self._active_repository_mcp,
                "other_mcp": tuple(
                    name
                    for name in self._active_mcp
                    if name != self._active_repository_mcp
                ),
                "allow_repository_git_pull": self._allow_repository_git_pull,
                "itsm_data": context.itsm if context else None,
                "ado_data": context.ado if context else None,
                "context_warnings": context.warnings if context else (),
                "ticket_type": context.ticket_type if context else "",
                "ai_instructions": context.ai_instructions if context else "",
            }
            prompt = (
                build_mcp_copilot_session_context(
                    workflow_id=self._workflow_id,
                    autodeploy_mcp_available=(
                        AUTODEPLOY_MCP_NAME in self._active_mcp
                    ),
                    **common,
                )
                if self._workflow_id
                else build_copilot_session_context(
                    form_catalog=self._catalog,
                    **common,
                )
            )
            self._client.add_session_context(
                session_id=self._require_session(),
                prompt=prompt,
                system=(
                    MCP_COPILOT_SYSTEM_RULES
                    if self._workflow_id
                    else COPILOT_SYSTEM_RULES
                ),
                agent=AUTODEPLOY_COPILOT_AGENT,
                provider_id=self._provider_id,
                model_id=self._model_id,
                variant=self._variant,
            )
            self._session_context_initialized = True
            self._current_environment = environment
            if ticket_id:
                self._sent_ticket_contexts.add(ticket_id)
            return

        updates: list[str] = []
        if environment != self._current_environment:
            updates.append(build_copilot_environment_context(environment))
        if context is not None and ticket_id not in self._sent_ticket_contexts:
            updates.append(build_copilot_ticket_context(
                ticket_id=ticket_id,
                environment=environment,
                itsm_data=context.itsm,
                ado_data=context.ado,
                context_warnings=context.warnings,
                ticket_type=context.ticket_type,
                ai_instructions=context.ai_instructions,
            ))
        if not updates:
            return
        notify("Добавляю новый контекст в текущую AI-сессию…")
        self._client.add_session_context(
            session_id=self._require_session(),
            prompt="\n\n".join(updates),
            system=(
                MCP_COPILOT_SYSTEM_RULES
                if self._workflow_id
                else COPILOT_SYSTEM_RULES
            ),
            agent=AUTODEPLOY_COPILOT_AGENT,
            provider_id=self._provider_id,
            model_id=self._model_id,
            variant=self._variant,
        )
        self._current_environment = environment
        if context is not None:
            self._sent_ticket_contexts.add(ticket_id)

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
        """Удаляет session при закрытии чата и очищает локальное состояние."""
        session_id = self._session_id
        self._session_id = None
        if session_id is not None:
            try:
                self._client.delete_session(session_id)
            except Exception:
                _log.warning("copilot session delete failed id=%s", session_id, exc_info=True)
        self._active_repository_mcp = ""
        self._active_mcp = ()
        self._session_context_initialized = False
        self._sent_ticket_contexts.clear()
        self._current_environment = ""
        self._part_states.clear()
        self._part_started_at.clear()
        self._pending_text_parts.clear()
        self._message_roles.clear()
        self._permission_ids.clear()
        self._last_session_status_signature = ""
        self._on_session(None)

    def _handle_raw_event(self, event: Mapping[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        props = event.get("properties")
        values = props if isinstance(props, dict) else {}
        if event_type == "client.sse.disconnected":
            # EventSource reconnects automatically.  This is transport noise,
            # not a conversation event, so keep it out of the chat transcript.
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
        if event_type == "message.updated":
            info = values.get("info")
            if not isinstance(info, dict):
                return
            message_id = str(info.get("id") or "")
            role = str(info.get("role") or "").casefold()
            if not message_id or not role:
                return
            with self._event_lock:
                self._message_roles[message_id] = role
                if role != "assistant":
                    for part_id, (part_message_id, _text) in tuple(
                        self._pending_text_parts.items()
                    ):
                        if part_message_id == message_id:
                            self._pending_text_parts.pop(part_id, None)
            return
        if event_type == "message.part.updated":
            part = values.get("part")
            if not isinstance(part, dict):
                return
            if part.get("type") == "text":
                self._remember_text_part(part, values.get("delta"))
                return
            if part.get("type") != "tool":
                return
            # A tool transition proves that all text received before it is
            # narration, not the final answer.  Flush it at this exact point so
            # AutoDeploy mirrors OpenCode Web without duplicating the final text.
            self._flush_pending_text_parts(str(part.get("messageID") or ""))
            part_id = str(part.get("id") or part.get("callID") or "")
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = str(state.get("status") or "updated")
            previous = self._part_states.get(part_id) if part_id else None
            if part_id:
                self._part_states[part_id] = status
            tool = str(part.get("tool") or state.get("title") or "MCP tool")
            if status == "pending":
                return
            if previous == status:
                return
            if part_id and status == "running":
                self._part_started_at.setdefault(part_id, time.monotonic())
            duration = self._tool_duration_seconds(
                state,
                self._part_started_at.pop(part_id, None)
                if part_id and status in {"completed", "error"}
                else self._part_started_at.get(part_id),
            )
            input_detail = self._safe_detail(state.get("input", ""))
            output_detail = self._safe_detail(
                state.get("error", "") if status == "error" else state.get("output", "")
            )
            detail = output_detail if status == "error" else input_detail
            self._emit(ConversationEvent(
                "error" if status == "error" else "tool",
                tool,
                detail,
                call_id=part_id,
                status=status,
                input_detail=input_detail,
                output_detail=output_detail,
                duration_seconds=duration,
            ))

    def _remember_text_part(self, part: Mapping[str, Any], delta: Any) -> None:
        message_id = str(part.get("messageID") or "")
        part_id = str(
            part.get("id")
            or f"{part.get('messageID', 'message')}:{len(self._pending_text_parts)}"
        )
        if not _assistant_text_part_allowed(part):
            with self._event_lock:
                self._pending_text_parts.pop(part_id, None)
            return
        full_text = part.get("text")
        with self._event_lock:
            if message_id and self._message_roles.get(message_id) not in {
                None,
                "assistant",
            }:
                self._pending_text_parts.pop(part_id, None)
                return
            if isinstance(full_text, str):
                self._pending_text_parts[part_id] = (message_id, full_text)
            elif isinstance(delta, str) and delta:
                previous = self._pending_text_parts.get(part_id)
                self._pending_text_parts[part_id] = (
                    message_id or (previous[0] if previous else ""),
                    (previous[1] if previous else "") + delta,
                )

    def _flush_pending_text_parts(self, assistant_message_id: str) -> None:
        with self._event_lock:
            pending: list[tuple[str, str]] = []
            for part_id, (message_id, value) in tuple(
                self._pending_text_parts.items()
            ):
                # OpenCode's SSE stream also publishes the user prompt.  Only
                # narration belonging to the same assistant message as the tool
                # may be exposed in chat.  Events without messageID are retained
                # solely for compatibility with older/test event payloads.
                matches = (
                    message_id == assistant_message_id
                    if assistant_message_id
                    else not message_id
                )
                if matches:
                    pending.append((part_id, value))
                    self._pending_text_parts.pop(part_id, None)
                    continue
                if message_id and self._message_roles.get(message_id) not in {
                    None,
                    "assistant",
                }:
                    self._pending_text_parts.pop(part_id, None)
        for part_id, value in pending:
            text = visible_assistant_text({"type": "text", "text": value})
            text = redact_text(text).strip()[:60_000]
            if text:
                self._emit(ConversationEvent(
                    "assistant_text",
                    "Copilot",
                    text,
                    call_id=part_id,
                    status="completed",
                ))

    def _discard_pending_text_parts(self) -> None:
        with self._event_lock:
            self._pending_text_parts.clear()
            self._message_roles.clear()

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

    @staticmethod
    def _safe_detail(value: Any) -> str:
        try:
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            rendered = str(value)
        return redact_text(rendered)[:12000]

    @staticmethod
    def _tool_duration_seconds(
        state: Mapping[str, Any], started_at: Optional[float]
    ) -> Optional[float]:
        timing = state.get("time")
        if isinstance(timing, Mapping):
            start = timing.get("start", timing.get("created"))
            end = timing.get("end", timing.get("completed"))
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
                # OpenCode timestamps are milliseconds since epoch.
                return round((float(end) - float(start)) / 1000.0, 3)
        if started_at is not None and str(state.get("status")) in {"completed", "error"}:
            return round(max(0.0, time.monotonic() - started_at), 3)
        return None

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
