"""Thread-safe web façade for the existing long-lived OpenCode agents."""
from __future__ import annotations

import dataclasses
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from config.environments import (
    ENVIRONMENT_MAP,
    OPENCODE_ALLOWED_MCP_KEY,
    OPENCODE_MAX_CONTEXT_CHARS_KEY,
    OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY,
    OPENCODE_REFERENCE_INLINE_MAX_ITEMS_KEY,
    OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY,
    OPENCODE_REPOSITORY_GIT_PULL_KEY,
    OPENCODE_REPOSITORY_MCP_KEY,
)
from config.mcp_profiles import AUTODEPLOY_MCP_NAME, AUTODEPLOY_MCP_TOOLS, setting_enabled
from forms.registry import FormRegistry
from opencode_integration.agent import ConversationEvent, FormExtractorAgent
from opencode_integration.copilot import CopilotOutcome, UnifiedCopilot, detect_ticket_reference
from opencode_integration.context_builder import BuiltContext, redact_text
from opencode_integration.thinking import decide_copilot_thinking, decide_extractor_thinking
from opencode_integration.workflow import ExtractionDirective


_log = logging.getLogger("web.ai")


@dataclass
class WebEvent:
    sequence: int
    kind: str
    timestamp: float
    payload: dict[str, Any]


@dataclass
class WebCopilotSession:
    id: str
    copilot: UnifiedCopilot
    provider_id: str
    model_id: str
    default_variant: str
    variants: tuple[str, ...]
    created_at: float = field(default_factory=time.time)
    events: list[WebEvent] = field(default_factory=list)
    sequence: int = 0
    busy: bool = False
    job_id: str = ""
    cancel_event: Optional[threading.Event] = None
    last_progress: str = ""
    operator_messages: list[str] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def emit(self, kind: str, payload: Mapping[str, Any]) -> WebEvent:
        with self.condition:
            self.sequence += 1
            event = WebEvent(
                self.sequence,
                kind,
                time.time(),
                dict(payload),
            )
            self.events.append(event)
            self.events = self.events[-1000:]
            self.condition.notify_all()
            return event

    def after(self, sequence: int, timeout: float = 15.0) -> list[WebEvent]:
        with self.condition:
            available = [item for item in self.events if item.sequence > sequence]
            if not available:
                self.condition.wait(timeout)
                available = [item for item in self.events if item.sequence > sequence]
            return list(available)


@dataclass(frozen=True)
class AIHandoff:
    token: str
    session_id: str
    form_id: str
    context: Any
    extraction: ExtractionDirective
    provider_id: str
    model_id: str
    variants: tuple[str, ...]
    created_at: float


@dataclass
class ExtractionJob:
    id: str
    handoff: AIHandoff
    environment: str
    current_values: dict[str, Any]
    status: str = "pending"
    progress: str = "Подготовка…"
    result: Optional[dict[str, Any]] = None
    error: str = ""
    agent: Optional[FormExtractorAgent] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class WebAIService:
    def __init__(self, container: Any) -> None:
        self.container = container
        self._sessions: dict[str, WebCopilotSession] = {}
        self._handoffs: dict[str, AIHandoff] = {}
        self._extractions: dict[str, ExtractionJob] = {}
        self._lock = threading.RLock()

    def create_session(self) -> dict[str, Any]:
        client = self.container.opencode_manager.client
        if client is None:
            raise RuntimeError("OpenCode Server не подключён")
        model_catalog = client.configured_model_catalog(agent_name="autodeploy-copilot")
        if not model_catalog.models:
            raise RuntimeError("В opencode.json не найдено настроенных моделей")
        selected = model_catalog.default
        if selected is None:
            first = model_catalog.models[0]
            provider_id, model_id, default_variant = first.provider_id, first.model_id, ""
        else:
            provider_id, model_id, default_variant = (
                selected.provider_id,
                selected.model_id,
                selected.variant,
            )
        model = next((
            item for item in model_catalog.models
            if item.provider_id == provider_id and item.model_id == model_id
        ), None)
        if model is None:
            raise RuntimeError(
                "Модель по умолчанию отсутствует среди доступных моделей opencode.json"
            )
        values = self.container.env_manager.load()
        services = self.container.service_provider(
            self.container.env_manager, self.container.new_http_client()
        )
        allowed_mcp = self._csv(values.get(OPENCODE_ALLOWED_MCP_KEY, ""))
        if self.container.settings.mcp_enabled:
            allowed_mcp = list(dict.fromkeys((*allowed_mcp, AUTODEPLOY_MCP_NAME)))
        copilot = UnifiedCopilot(
            client,
            services.itsm,
            services.tfs,
            forms=FormRegistry().all_forms(),
            allowed_mcp=allowed_mcp,
            repository_mcp=values.get(OPENCODE_REPOSITORY_MCP_KEY, ""),
            allow_repository_git_pull=setting_enabled(
                values.get(OPENCODE_REPOSITORY_GIT_PULL_KEY), default=True
            ),
            max_context_chars=self._integer(
                values.get(OPENCODE_MAX_CONTEXT_CHARS_KEY), 120_000
            ),
            trusted_mcp_tools=(
                {AUTODEPLOY_MCP_NAME: AUTODEPLOY_MCP_TOOLS}
                if self.container.settings.mcp_enabled
                else {}
            ),
        )
        session_id = secrets.token_urlsafe(24)
        session = WebCopilotSession(
            id=session_id,
            copilot=copilot,
            provider_id=provider_id,
            model_id=model_id,
            default_variant=default_variant,
            variants=tuple(model.variants),
        )
        session.emit("system", {
            "title": "Сессия готова",
            "detail": "История и контекст сохраняются между сообщениями.",
        })
        with self._lock:
            self._sessions[session_id] = session
        return self.snapshot(session_id, include_events=True)

    def snapshot(self, session_id: str, *, include_events: bool = True) -> dict[str, Any]:
        session = self._session(session_id)
        return {
            "id": session.id,
            "busy": session.busy,
            "job_id": session.job_id or None,
            "provider_id": session.provider_id,
            "model_id": session.model_id,
            "default_variant": session.default_variant,
            "variants": list(session.variants),
            "opencode_session_id": session.copilot.session_id,
            "opencode_url": (
                self.container.opencode_manager.client.session_web_url(session.copilot.session_id)
                if self.container.opencode_manager.client and session.copilot.session_id
                else None
            ),
            "events": [dataclasses.asdict(item) for item in session.events] if include_events else [],
        }

    def start_message(
        self,
        session_id: str,
        *,
        message: str,
        environment: str,
        ticket_id: Optional[str],
        provider_id: str,
        model_id: str,
        thinking: str,
    ) -> dict[str, Any]:
        if environment not in ENVIRONMENT_MAP:
            raise ValueError("Неизвестное окружение")
        session = self._session(session_id)
        with session.condition:
            if session.busy:
                raise RuntimeError("Предыдущий запрос ещё выполняется")
            selected_provider = provider_id.strip() or session.provider_id
            selected_model = model_id.strip() or session.model_id
            variants = self._model_variants(selected_provider, selected_model)
            actual_thinking, thinking_reason = self._resolve_copilot_thinking(
                thinking,
                variants,
                bool(ticket_id or detect_ticket_reference(message)),
            )
            session.provider_id = selected_provider
            session.model_id = selected_model
            session.variants = variants
            session.busy = True
            session.job_id = secrets.token_urlsafe(16)
            session.cancel_event = threading.Event()
            session.last_progress = ""
            job_id = session.job_id
        session.emit("user", {"text": message, "thinking": actual_thinking})
        clean_message = redact_text(message.strip())[:20_000]
        session.operator_messages.append(clean_message)
        # This history is used only when handing work to the separate extractor
        # session.  The copilot itself already has native OpenCode session memory.
        while len(session.operator_messages) > 30 or sum(
            len(item) for item in session.operator_messages
        ) > 60_000:
            session.operator_messages.pop(0)
        session.emit("progress", {
            "text": "OpenCode начинает обработку",
            "thinking": actual_thinking,
            "thinking_reason": thinking_reason,
        })

        def worker() -> None:
            started = time.monotonic()

            def progress(text: str) -> None:
                clean = str(text).strip()
                if not clean or clean == session.last_progress:
                    return
                session.last_progress = clean
                session.emit("progress", {"text": clean})

            def conversation(event: ConversationEvent) -> None:
                session.emit("agent_event", dataclasses.asdict(event))

            try:
                outcome = session.copilot.ask(
                    message,
                    environment=environment,
                    ticket_id=ticket_id,
                    provider_id=selected_provider,
                    model_id=selected_model,
                    variant=actual_thinking,
                    cancel_event=session.cancel_event,
                    on_progress=progress,
                    on_event=conversation,
                )
                payload = self._outcome_payload(session, outcome)
                payload["thinking"] = actual_thinking
                payload["elapsed_seconds"] = outcome.elapsed_seconds or (time.monotonic() - started)
                session.emit("assistant", payload)
            except Exception as exc:
                cancelled = bool(session.cancel_event and session.cancel_event.is_set())
                _log.warning(
                    "web copilot request failed session=%s error_type=%s",
                    session_id,
                    type(exc).__name__,
                    exc_info=True,
                )
                session.emit("cancelled" if cancelled else "error", {
                    "message": "Запрос отменён" if cancelled else str(exc),
                    "error_type": type(exc).__name__,
                    "elapsed_seconds": time.monotonic() - started,
                })
            finally:
                with session.condition:
                    if session.job_id == job_id:
                        session.busy = False
                        session.job_id = ""
                        session.cancel_event = None
                session.emit("idle", {})

        threading.Thread(
            target=worker,
            name=f"web-copilot-{job_id}",
            daemon=True,
        ).start()
        return {"job_id": job_id, "thinking": actual_thinking}

    def cancel(self, session_id: str) -> None:
        session = self._session(session_id)
        if session.cancel_event:
            session.cancel_event.set()
        session.copilot.cancel()

    def permission(self, session_id: str, permission_id: str, allow: bool) -> None:
        self._session(session_id).copilot.approve_permission(permission_id, allow=allow)

    def delete(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.copilot.cancel()
            session.copilot.close()

    def events_after(self, session_id: str, sequence: int, timeout: float = 15.0) -> list[WebEvent]:
        return self._session(session_id).after(sequence, timeout)

    def start_extraction(
        self,
        token: str,
        environment: str,
        current_values: Mapping[str, Any],
    ) -> dict[str, Any]:
        if environment not in ENVIRONMENT_MAP:
            raise ValueError("Неизвестное окружение")
        handoff = self._take_handoff(token)
        job_id = secrets.token_urlsafe(20)
        job = ExtractionJob(job_id, handoff, environment, dict(current_values))
        with self._lock:
            self._extractions[job_id] = job
        threading.Thread(
            target=self._extract_worker,
            args=(job,),
            name=f"web-extractor-{job_id}",
            daemon=True,
        ).start()
        return {"job_id": job_id, "status": job.status}

    def extraction(self, job_id: str) -> dict[str, Any]:
        job = self._extraction(job_id)
        with job.lock:
            return {
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "result": job.result,
                "error": job.error,
            }

    def refine_extraction(self, job_id: str, guidance: str) -> dict[str, Any]:
        job = self._extraction(job_id)
        with job.lock:
            if job.status == "running":
                raise RuntimeError("Extractor уже выполняет запрос")
            if job.agent is None or job.result is None:
                raise RuntimeError("Активная extractor session отсутствует")
            job.status = "running"
            job.progress = "Применяю уточнение…"
            job.error = ""

        def worker() -> None:
            try:
                assert job.agent is not None
                job.agent.send_guidance(guidance)
                result = job.agent.finalize()
                with job.lock:
                    job.result = self._validated_payload(result)
                    job.status = "complete"
                    job.progress = "Предложения обновлены"
            except Exception as exc:
                with job.lock:
                    job.status = "error"
                    job.error = str(exc)

        threading.Thread(target=worker, name=f"web-refine-{job.id}", daemon=True).start()
        return self.extraction(job_id)

    def close_extraction(self, job_id: str, *, cancel: bool = False) -> None:
        with self._lock:
            job = self._extractions.pop(job_id, None)
        if job is None:
            raise KeyError("Extractor job не найден")
        if cancel:
            job.cancel_event.set()
            if job.agent:
                job.agent.cancel()
        if job.agent:
            job.agent.close()
            job.agent = None

    def close(self) -> None:
        with self._lock:
            session_ids = list(self._sessions)
            extraction_ids = list(self._extractions)
        for job_id in extraction_ids:
            try:
                self.close_extraction(job_id, cancel=True)
            except Exception:
                pass
        for session_id in session_ids:
            self.delete(session_id)

    def _extract_worker(self, job: ExtractionJob) -> None:
        try:
            self._run_extraction(job)
        except Exception as exc:
            _log.warning(
                "web extractor setup failed job=%s error_type=%s",
                job.id,
                type(exc).__name__,
                exc_info=True,
            )
            with job.lock:
                job.status = "cancelled" if job.cancel_event.is_set() else "error"
                job.error = (
                    "Операция отменена" if job.cancel_event.is_set() else str(exc)
                )

    def _run_extraction(self, job: ExtractionJob) -> None:
        handoff = job.handoff
        directive = handoff.extraction
        values = self.container.env_manager.load()
        client = self.container.opencode_manager.client
        if client is None:
            with job.lock:
                job.status, job.error = "error", "OpenCode Server не подключён"
            return
        services = self.container.service_provider(
            self.container.env_manager, self.container.new_http_client()
        )
        agent = FormExtractorAgent(
            client,
            services.itsm,
            services.tfs,
            reference_resolver=self.container.new_reference_resolver(),
            max_context_chars=self._integer(values.get(OPENCODE_MAX_CONTEXT_CHARS_KEY), 120_000),
            inline_reference_max_items=self._integer(values.get(OPENCODE_REFERENCE_INLINE_MAX_ITEMS_KEY), 99),
            inline_reference_max_bytes=self._integer(values.get(OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY), 24_576),
            inline_reference_total_bytes=self._integer(values.get(OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY), 49_152),
        )
        job.agent = agent
        with job.lock:
            job.status = "running"
            job.progress = "Extractor анализирует форму…"
        actual_variant = decide_extractor_thinking(
            directive.mode,
            missing_information=directive.missing_information,
            research_goal=directive.research_goal,
            available_variants=handoff.variants,
        ).variant

        def progress(text: str) -> None:
            with job.lock:
                job.progress = str(text)

        try:
            form = self.container.forms.get_form(handoff.form_id)
            if directive.mode == "fill_only":
                result = agent.fill_only(
                    form=form,
                    ticket_id=getattr(handoff.context, "ticket_id", ""),
                    environment=job.environment,
                    current_values=job.current_values,
                    field_proposals=[dataclasses.asdict(item) for item in directive.field_proposals],
                    provider_id=handoff.provider_id,
                    model_id=handoff.model_id,
                    variant=actual_variant,
                    cancel_event=job.cancel_event,
                    prepared_context=handoff.context,
                    on_progress=progress,
                )
            else:
                agent.begin(
                    form=form,
                    ticket_id=getattr(handoff.context, "ticket_id", ""),
                    environment=job.environment,
                    current_values=job.current_values,
                    allowed_mcp=self._csv(values.get(OPENCODE_ALLOWED_MCP_KEY, "")),
                    repository_mcp=values.get(OPENCODE_REPOSITORY_MCP_KEY, ""),
                    allow_repository_git_pull=setting_enabled(
                        values.get(OPENCODE_REPOSITORY_GIT_PULL_KEY), default=True
                    ),
                    plan_guidance=directive.research_goal,
                    provider_id=handoff.provider_id,
                    model_id=handoff.model_id,
                    variant=actual_variant,
                    cancel_event=job.cancel_event,
                    prepared_context=handoff.context,
                    on_progress=progress,
                )
                result = agent.finalize()
            with job.lock:
                job.result = self._validated_payload(result)
                job.status = "complete"
                job.progress = "Предложения готовы"
        except Exception as exc:
            _log.warning("web extractor failed job=%s error_type=%s", job.id, type(exc).__name__, exc_info=True)
            with job.lock:
                job.status = "cancelled" if job.cancel_event.is_set() else "error"
                job.error = "Операция отменена" if job.cancel_event.is_set() else str(exc)

    def _outcome_payload(self, session: WebCopilotSession, outcome: CopilotOutcome) -> dict[str, Any]:
        handoff_token = None
        if outcome.selected_form_id and outcome.extraction and outcome.context is not None:
            context = self._context_with_operator_history(
                outcome.context, session.operator_messages
            )
            handoff_token = secrets.token_urlsafe(32)
            with self._lock:
                threshold = time.time() - 24 * 3600
                self._handoffs = {
                    key: value
                    for key, value in self._handoffs.items()
                    if value.created_at >= threshold
                }
                self._handoffs[handoff_token] = AIHandoff(
                    handoff_token,
                    session.id,
                    outcome.selected_form_id,
                    context,
                    outcome.extraction,
                    session.provider_id,
                    session.model_id,
                    session.variants,
                    time.time(),
                )
        return {
            "text": outcome.answer,
            "question": outcome.question,
            "intent": outcome.intent,
            "selected_form_id": outcome.selected_form_id,
            "handoff_token": handoff_token,
            "form_candidates": [dataclasses.asdict(item) for item in outcome.form_candidates],
            "repository_items": [dataclasses.asdict(item) for item in outcome.repository_items],
            "diagnostics": dataclasses.asdict(outcome.diagnostics) if outcome.diagnostics else None,
            "plan": [dataclasses.asdict(item) for item in outcome.plan],
            "warnings": list(outcome.warnings),
            "opencode_seconds": outcome.opencode_seconds,
            "generation_seconds": outcome.generation_seconds,
        }

    @staticmethod
    def _context_with_operator_history(
        context: BuiltContext,
        messages: list[str],
    ) -> BuiltContext:
        """Give the isolated extractor the relevant chat, without resending it
        on every copilot turn or relying on cross-session OpenCode memory.
        """
        if isinstance(context.itsm, Mapping):
            itsm = copy_json(context.itsm)
        elif context.itsm is None:
            itsm = {}
        else:
            itsm = {"ticket_data": copy_json(context.itsm)}
        itsm["operator_conversation"] = list(messages)
        return dataclasses.replace(context, itsm=itsm)

    @staticmethod
    def _validated_payload(result: Any) -> dict[str, Any]:
        return {
            "values": copy_json(result.form_data),
            "warnings": list(result.warnings),
            "fields": [
                {
                    "key": item.key,
                    "label": item.label,
                    "current_value": copy_json(item.current_value),
                    "proposed_value": copy_json(item.proposed_value),
                    "confidence": item.confidence,
                    "source": item.source,
                    "reason": item.reason,
                    "conflict": item.conflict,
                    "candidates": [list(value) for value in item.candidates],
                }
                for item in result.preview_fields
            ],
        }

    def _resolve_copilot_thinking(
        self, requested: str, variants: tuple[str, ...], has_ticket: bool
    ) -> tuple[str, str]:
        clean = requested.strip().casefold() or "auto"
        if clean == "auto":
            decision = decide_copilot_thinking(
                has_ticket=has_ticket,
                available_variants=variants,
            )
            return decision.variant, decision.reason
        mapping = {item.casefold(): item for item in variants}
        if clean not in mapping:
            raise ValueError(f"Thinking variant {requested!r} отсутствует в opencode.json")
        return mapping[clean], "уровень выбран пользователем"

    def _model_variants(self, provider_id: str, model_id: str) -> tuple[str, ...]:
        client = self.container.opencode_manager.client
        if client is None:
            raise RuntimeError("OpenCode Server не подключён")
        catalog = client.configured_model_catalog(agent_name="autodeploy-copilot")
        for item in catalog.models:
            if item.provider_id == provider_id and item.model_id == model_id:
                return tuple(item.variants)
        raise ValueError("Выбранная модель отсутствует в opencode.json")

    def _session(self, session_id: str) -> WebCopilotSession:
        with self._lock:
            value = self._sessions.get(session_id)
        if value is None:
            raise KeyError("AI session не найдена")
        return value

    def _take_handoff(self, token: str) -> AIHandoff:
        with self._lock:
            value = self._handoffs.pop(token, None)
        if value is None or value.created_at < time.time() - 24 * 3600:
            raise KeyError("AI handoff не найден или истёк")
        return value

    def _extraction(self, job_id: str) -> ExtractionJob:
        with self._lock:
            value = self._extractions.get(job_id)
        if value is None:
            raise KeyError("Extractor job не найден")
        return value

    @staticmethod
    def _csv(value: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.strip() for item in str(value).split(",") if item.strip()))

    @staticmethod
    def _integer(value: Any, default: int) -> int:
        try:
            result = int(value)
            return result if result > 0 else default
        except (TypeError, ValueError):
            return default


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
