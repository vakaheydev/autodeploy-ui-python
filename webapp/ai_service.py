"""Thread-safe web façade for the existing long-lived OpenCode agents."""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

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
from config.mcp_profiles import (
    AUTODEPLOY_COPILOT_TOOLS,
    AUTODEPLOY_MCP_NAME,
    setting_enabled,
)
from forms.registry import FormRegistry
from opencode_integration.agent import ConversationEvent, FormExtractorAgent
from opencode_integration.client import opencode_message_duration
from opencode_integration.copilot import CopilotOutcome, UnifiedCopilot, detect_ticket_reference
from opencode_integration.context_builder import BuiltContext, redact_text
from opencode_integration.form_search import SemanticFormSearchSession
from opencode_integration.researcher import RepositoryResearcher
from opencode_integration.thinking import decide_copilot_thinking, decide_extractor_thinking
from opencode_integration.workflow import ExtractionDirective
from webapp.ai_drafts import FormDraftStore
from webapp.form_runtime import form_version


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
    form_search: SemanticFormSearchSession
    created_at: float = field(default_factory=time.time)
    events: list[WebEvent] = field(default_factory=list)
    sequence: int = 0
    busy: bool = False
    job_id: str = ""
    cancel_event: Optional[threading.Event] = None
    last_progress: str = ""
    operator_messages: list[str] = field(default_factory=list)
    turn_candidates: list[dict[str, Any]] = field(default_factory=list)
    turn_candidates_job_id: str = ""
    turn_draft_id: str = ""
    turn_draft_ids: list[str] = field(default_factory=list)
    turn_draft_job_id: str = ""
    refining_draft_id: str = ""
    active_environment: str = ""
    active_researcher: Optional[RepositoryResearcher] = None
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
    draft_id: str = ""
    agent: Optional[FormExtractorAgent] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class WebAIService:
    def __init__(self, container: Any) -> None:
        self.container = container
        self._sessions: dict[str, WebCopilotSession] = {}
        self._handoffs: dict[str, AIHandoff] = {}
        self._extractions: dict[str, ExtractionJob] = {}
        self._drafts = FormDraftStore(container)
        self._lock = threading.RLock()
        self._session_discovery_at = 0.0
        self._session_discovery_client = 0

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
        workflow_id = secrets.token_urlsafe(24)
        session = self._compose_session(
            workflow_id=workflow_id,
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
            self._sessions[workflow_id] = session
        return self.snapshot(workflow_id, include_events=True)

    def _compose_session(
        self,
        *,
        workflow_id: str,
        provider_id: str,
        model_id: str,
        default_variant: str,
        variants: tuple[str, ...],
        opencode_session_id: str = "",
        created_at: Optional[float] = None,
        events: Optional[list[WebEvent]] = None,
    ) -> WebCopilotSession:
        client = self.container.opencode_manager.client
        if client is None:
            raise RuntimeError("OpenCode Server не подключён")
        values = self.container.env_manager.load()
        services = self.container.service_provider(
            self.container.env_manager, self.container.new_http_client()
        )
        allowed_mcp = self._csv(values.get(OPENCODE_ALLOWED_MCP_KEY, ""))
        if self.container.settings.mcp_enabled:
            allowed_mcp = list(dict.fromkeys((*allowed_mcp, AUTODEPLOY_MCP_NAME)))
        forms = tuple(FormRegistry().all_forms())
        copilot = UnifiedCopilot(
            client,
            services.itsm,
            services.tfs,
            forms=forms,
            allowed_mcp=allowed_mcp,
            repository_mcp=values.get(OPENCODE_REPOSITORY_MCP_KEY, ""),
            allow_repository_git_pull=setting_enabled(
                values.get(OPENCODE_REPOSITORY_GIT_PULL_KEY), default=True
            ),
            max_context_chars=self._integer(
                values.get(OPENCODE_MAX_CONTEXT_CHARS_KEY), 120_000
            ),
            trusted_mcp_tools=(
                {AUTODEPLOY_MCP_NAME: AUTODEPLOY_COPILOT_TOOLS}
                if self.container.settings.mcp_enabled
                else {}
            ),
            workflow_id=workflow_id,
        )
        if opencode_session_id:
            copilot.resume_session(opencode_session_id)
        restored_events = list(events or [])
        return WebCopilotSession(
            id=workflow_id,
            copilot=copilot,
            provider_id=provider_id,
            model_id=model_id,
            default_variant=default_variant,
            variants=variants,
            form_search=SemanticFormSearchSession(client, forms=forms),
            created_at=created_at or time.time(),
            events=restored_events,
            sequence=max((event.sequence for event in restored_events), default=0),
        )

    def list_sessions(self) -> dict[str, Any]:
        """List Copilot workflows that can be resumed by the web client.

        OpenCode persists its own session transcript.  This list intentionally
        contains only sessions created through AutoDeploy because they also own
        Python-side draft, permission and form-search state.
        """
        self._restore_sessions_from_opencode()
        with self._lock:
            sessions = list(self._sessions.values())
        items = []
        for session in sessions:
            first_user = next(
                (
                    str(event.payload.get("text") or "").strip()
                    for event in session.events
                    if event.kind == "user"
                ),
                "",
            )
            updated_at = (
                session.events[-1].timestamp
                if session.events
                else session.created_at
            )
            items.append({
                "id": session.id,
                "title": first_user[:80] or "Новый диалог",
                "created_at": session.created_at,
                "updated_at": updated_at,
                "busy": session.busy,
                "provider_id": session.provider_id,
                "model_id": session.model_id,
                "opencode_session_id": session.copilot.session_id,
            })
        items.sort(key=lambda item: float(item["updated_at"]), reverse=True)
        return {"items": items}

    def _restore_sessions_from_opencode(self) -> None:
        client = self.container.opencode_manager.client
        if client is None:
            return
        now = time.monotonic()
        client_identity = id(client)
        with self._lock:
            if (
                self._session_discovery_client == client_identity
                and now - self._session_discovery_at < 5.0
            ):
                return
            self._session_discovery_client = client_identity
            self._session_discovery_at = now
        try:
            remote_sessions = client.list_sessions(timeout=min(10.0, client.timeout))
            catalog = client.configured_model_catalog(agent_name="autodeploy-copilot")
        except Exception:
            _log.debug("opencode session discovery failed", exc_info=True)
            return
        default = catalog.default
        fallback_model = catalog.models[0] if catalog.models else None
        for remote in remote_sessions:
            metadata = remote.get("metadata")
            if (
                not isinstance(metadata, Mapping)
                or metadata.get("source") != "gravitee-autodeploy-ui-copilot"
            ):
                continue
            workflow_id = str(metadata.get("workflow_id") or "").strip()
            remote_id = str(remote.get("id") or "").strip()
            if not workflow_id or not remote_id:
                continue
            with self._lock:
                if workflow_id in self._sessions:
                    continue
            raw_model = (
                remote.get("model")
                if isinstance(remote.get("model"), Mapping)
                else {}
            )
            provider_id = str(
                raw_model.get("providerID")
                or (default.provider_id if default else "")
                or (fallback_model.provider_id if fallback_model else "")
            )
            model_id = str(
                raw_model.get("modelID")
                or raw_model.get("id")
                or (default.model_id if default else "")
                or (fallback_model.model_id if fallback_model else "")
            )
            model = next(
                (
                    item
                    for item in catalog.models
                    if item.provider_id == provider_id and item.model_id == model_id
                ),
                fallback_model,
            )
            if model is None:
                continue
            try:
                history = self._history_from_opencode(client.list_session_messages(remote_id))
                raw_time = remote.get("time") if isinstance(remote.get("time"), Mapping) else {}
                created_at = self._timestamp_seconds(raw_time.get("created")) or time.time()
                restored = self._compose_session(
                    workflow_id=workflow_id,
                    provider_id=provider_id,
                    model_id=model_id,
                    default_variant=str(
                        raw_model.get("variant")
                        or (default.variant if default else "")
                    ),
                    variants=tuple(model.variants),
                    opencode_session_id=remote_id,
                    created_at=created_at,
                    events=history,
                )
            except Exception:
                _log.debug("opencode session restore failed id=%s", remote_id, exc_info=True)
                continue
            with self._lock:
                self._sessions.setdefault(workflow_id, restored)

    @classmethod
    def _history_from_opencode(
        cls, messages: Sequence[Mapping[str, Any]]
    ) -> list[WebEvent]:
        events: list[WebEvent] = []
        sequence = 0
        for message in messages:
            info = (
                message.get("info")
                if isinstance(message.get("info"), Mapping)
                else {}
            )
            parts = (
                message.get("parts")
                if isinstance(message.get("parts"), (list, tuple))
                else ()
            )
            role = str(info.get("role") or "")
            timestamp = cls._timestamp_seconds(
                (info.get("time") if isinstance(info.get("time"), Mapping) else {}).get("created")
            ) or time.time()
            if role == "user":
                raw_text = "\n".join(
                    str(part.get("text") or "")
                    for part in parts
                    if isinstance(part, Mapping) and part.get("type") == "text"
                )
                match = re.search(
                    r"BEGIN_OPERATOR_REQUEST\s*(.*?)\s*END_OPERATOR_REQUEST",
                    raw_text,
                    re.DOTALL,
                )
                if not match:
                    continue
                operator_text = match.group(1).strip()
                try:
                    parsed = json.loads(operator_text)
                    operator_text = str(parsed)
                except Exception:
                    pass
                sequence += 1
                events.append(WebEvent(
                    sequence,
                    "user",
                    timestamp,
                    {
                        "text": operator_text,
                        "thinking": str(info.get("variant") or "—"),
                    },
                ))
                continue
            if role != "assistant":
                continue
            message_drafts: list[dict[str, Any]] = []
            for part in parts:
                if not isinstance(part, Mapping) or part.get("type") != "tool":
                    continue
                state = part.get("state") if isinstance(part.get("state"), Mapping) else {}
                status = str(state.get("status") or "completed")
                output_value = state.get("output", "")
                tool_name = str(part.get("tool") or state.get("title") or "MCP tool")
                decoded_output: Any = output_value
                if isinstance(decoded_output, str):
                    try:
                        decoded_output = json.loads(decoded_output)
                    except (TypeError, ValueError):
                        pass
                if (
                    status == "completed"
                    and tool_name.endswith("prepare_form_draft")
                    and isinstance(decoded_output, Mapping)
                    and decoded_output.get("draft_id")
                    and decoded_output.get("form_id")
                ):
                    message_drafts.append({
                        "draft_id": str(decoded_output["draft_id"]),
                        "form_id": str(decoded_output["form_id"]),
                        "environment": str(decoded_output.get("environment") or ""),
                        "valid": bool(decoded_output.get("valid")),
                        "revision": int(decoded_output.get("revision") or 1),
                    })
                sequence += 1
                event = ConversationEvent(
                    "error" if status == "error" else "tool",
                    tool_name,
                    cls._safe_detail(state.get("input", "")),
                    call_id=str(part.get("id") or part.get("callID") or ""),
                    status=status,
                    input_detail=cls._safe_detail(state.get("input", "")),
                    output_detail=cls._safe_detail(
                        state.get("error", "")
                        if status == "error"
                        else state.get("output", "")
                    ),
                    duration_seconds=UnifiedCopilot._tool_duration_seconds(
                        state, None
                    ),
                )
                events.append(WebEvent(
                    sequence,
                    "agent_event",
                    timestamp,
                    dataclasses.asdict(event),
                ))
            answer = "\n".join(
                str(part.get("text") or "")
                for part in parts
                if isinstance(part, Mapping) and part.get("type") == "text"
            ).strip()
            if answer:
                sequence += 1
                assistant_payload = {
                    "text": answer,
                    "thinking": str(info.get("variant") or "—"),
                    "elapsed_seconds": opencode_message_duration(info),
                }
                if len(message_drafts) == 1:
                    assistant_payload.update({
                        "intent": "single_form",
                        "selected_form_id": message_drafts[0]["form_id"],
                        "draft_id": message_drafts[0]["draft_id"],
                    })
                elif message_drafts:
                    assistant_payload.update({
                        "intent": "execution_plan",
                        "drafts": message_drafts,
                    })
                events.append(WebEvent(sequence, "assistant", timestamp, assistant_payload))
        if events:
            events.insert(0, WebEvent(0, "system", events[0].timestamp, {
                "title": "Сессия восстановлена из OpenCode",
                "detail": "История загружена с локального OpenCode Server.",
            }))
        return events[-1000:]

    @staticmethod
    def _timestamp_seconds(value: Any) -> Optional[float]:
        if not isinstance(value, (int, float)) or value <= 0:
            return None
        return float(value) / 1000.0 if value > 10_000_000_000 else float(value)

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
            "form_search_session_id": session.form_search.session_id,
            "form_search_url": (
                self.container.opencode_manager.client.session_web_url(
                    session.form_search.session_id
                )
                if self.container.opencode_manager.client
                and session.form_search.session_id
                else None
            ),
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
        draft_context: Any = None,
        refining_draft_id: str = "",
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
            session.turn_candidates = []
            session.turn_candidates_job_id = ""
            session.turn_draft_id = ""
            session.turn_draft_ids = []
            session.turn_draft_job_id = ""
            session.refining_draft_id = refining_draft_id
            session.active_environment = environment
            job_id = session.job_id
        session.emit("user", {"text": message, "thinking": actual_thinking})
        clean_message = redact_text(message.strip())[:20_000]
        if not session.copilot.mcp_native:
            session.operator_messages.append(clean_message)
            # Legacy extractor handoff only. OpenCode already owns Copilot history.
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
                    draft_context=draft_context,
                )
                payload = self._outcome_payload(session, outcome)
                payload["thinking"] = actual_thinking
                payload["elapsed_seconds"] = outcome.elapsed_seconds or (time.monotonic() - started)
                session.emit("assistant", payload)
                if (
                    refining_draft_id
                    and refining_draft_id not in session.turn_draft_ids
                ):
                    self._drafts.fail(
                        refining_draft_id,
                        "Copilot не обновил черновик. "
                        + (outcome.answer.strip()[:1500] or "Требуется уточнение."),
                    )
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
                if refining_draft_id:
                    self._drafts.fail(
                        refining_draft_id,
                        "Запрос отменён" if cancelled else str(exc),
                    )
            finally:
                with session.condition:
                    if session.job_id == job_id:
                        session.busy = False
                        session.job_id = ""
                        session.cancel_event = None
                        session.refining_draft_id = ""
                        session.active_environment = ""
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
        session.form_search.cancel()
        if session.active_researcher:
            session.active_researcher.cancel()

    def permission(self, session_id: str, permission_id: str, allow: bool) -> None:
        self._session(session_id).copilot.approve_permission(permission_id, allow=allow)

    def delete(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            if session.busy:
                session.copilot.cancel()
            session.copilot.close()
            session.form_search.close()
            if session.active_researcher:
                session.active_researcher.cancel()
                session.active_researcher.close()
            self._drafts.delete_workflow(session.id)

    def semantic_search_forms(
        self,
        workflow_id: str,
        *,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Run one query in the lazy search session owned by this chat."""
        session, job_id = self._active_workflow(workflow_id)
        none_variant = self._exact_variant(session.variants, "none")
        if not none_variant:
            raise RuntimeError(
                "Для семантического поиска у выбранной модели должен быть "
                "thinking variant 'none' в opencode.json"
            )
        result = session.form_search.search(
            query,
            provider_id=session.provider_id,
            model_id=session.model_id,
            none_variant=none_variant,
            limit=limit,
            cancel_event=session.cancel_event,
        )
        items = [
            {
                **copy_json(candidate.description),
                "score": candidate.score,
                "reason": candidate.reason,
            }
            for candidate in result.candidates
        ]
        with session.condition:
            if session.job_id != job_id:
                raise RuntimeError("Запрос семантического поиска уже не активен")
            session.turn_candidates = items
            session.turn_candidates_job_id = job_id
        return {
            "items": items,
            "total": len(items),
            "search_session_id": result.session_id,
            "thinking": none_variant,
        }

    def prepare_form_draft(
        self,
        workflow_id: str,
        *,
        form_id: str,
        environment: str,
        form_version: str,
        proposals: Sequence[Mapping[str, Any]],
        draft_id: str = "",
    ) -> dict[str, Any]:
        """Validate an MCP proposal and correlate its local draft to the turn."""
        session, job_id = self._active_workflow(workflow_id)
        self._require_active_environment(session, environment)
        if session.refining_draft_id and draft_id != session.refining_draft_id:
            raise ValueError(
                "Уточнение должно обновить переданный draft_id, а не создать новый"
            )
        draft = self._drafts.prepare(
            workflow_id=workflow_id,
            form_id=str(form_id),
            environment=str(environment),
            version=str(form_version),
            proposals=proposals,
            draft_id=str(draft_id),
            cancel_event=session.cancel_event,
        )
        with session.condition:
            if session.job_id != job_id:
                if not draft_id:
                    self._drafts.delete(draft.id, workflow_id=workflow_id)
                raise RuntimeError("Запрос подготовки черновика уже не активен")
            session.turn_draft_id = draft.id
            if draft.id not in session.turn_draft_ids:
                session.turn_draft_ids.append(draft.id)
            session.turn_draft_job_id = job_id
        snapshot = draft.snapshot()
        result = snapshot.get("result") or {}
        return {
            "draft_id": draft.id,
            "form_id": draft.form_id,
            "environment": draft.environment,
            "form_version": draft.form_version,
            "revision": draft.revision,
            "status": draft.status,
            "valid": bool(result.get("valid")),
            "proposal_count": len(result.get("fields") or []),
            "validation_errors": copy_json(result.get("errors") or [])[:30],
            "warnings": list(result.get("warnings") or [])[:30],
            "review_url": f"/forms/{draft.form_id}",
            "submitted": False,
        }

    def research_repository(
        self,
        workflow_id: str,
        *,
        question: str,
        environment: str,
        required_facts: Sequence[str] = (),
        depth: str = "focused",
    ) -> dict[str, Any]:
        """Delegate one bounded complex lookup without polluting chat memory."""
        session, job_id = self._active_workflow(workflow_id)
        self._require_active_environment(session, environment)
        repository_mcp = session.copilot.repository_mcp
        if not repository_mcp:
            raise RuntimeError("JSON Repository MCP не подключён к Copilot")
        clean_depth = str(depth).strip().casefold()
        if clean_depth not in {"focused", "deep"}:
            raise ValueError("depth должен быть focused или deep")
        desired = "xhigh" if clean_depth == "deep" else "low"
        variant = self._best_variant(session.variants, desired)
        client = self.container.opencode_manager.client
        if client is None:
            raise RuntimeError("OpenCode Server не подключён")
        researcher = RepositoryResearcher(client)
        part_states: dict[str, str] = {}
        part_started_at: dict[str, float] = {}

        def research_event(raw: dict[str, Any]) -> None:
            event_type = str(raw.get("type") or "")
            properties = raw.get("properties")
            values = properties if isinstance(properties, Mapping) else {}
            if event_type == "client.sse.disconnected":
                # The OpenCode client reconnects by itself; a transient SSE
                # disconnect is only useful in server logs, not in the chat.
                return
            if event_type != "message.part.updated":
                return
            part = values.get("part")
            if not isinstance(part, Mapping) or part.get("type") != "tool":
                return
            state = part.get("state") if isinstance(part.get("state"), Mapping) else {}
            status = str(state.get("status") or "updated")
            part_id = str(part.get("id") or part.get("callID") or "")
            previous = part_states.get(part_id) if part_id else None
            if part_id:
                part_states[part_id] = status
            if status == "pending" or status == previous:
                return
            title = str(part.get("tool") or state.get("title") or "MCP tool")
            if part_id and status == "running":
                part_started_at.setdefault(part_id, time.monotonic())
            started_at = (
                part_started_at.pop(part_id, None)
                if part_id and status in {"completed", "error"}
                else part_started_at.get(part_id)
            )
            duration = UnifiedCopilot._tool_duration_seconds(state, started_at)
            input_detail = self._safe_detail(state.get("input", ""))
            output_detail = self._safe_detail(
                state.get("error", "") if status == "error" else state.get("output", "")
            )
            session.emit("agent_event", dataclasses.asdict(ConversationEvent(
                "error" if status == "error" else "tool",
                f"Researcher · {title}",
                output_detail if status == "error" else input_detail,
                call_id=f"researcher:{part_id}" if part_id else "",
                status=status,
                input_detail=input_detail,
                output_detail=output_detail,
                duration_seconds=duration,
            )))

        with session.condition:
            if session.job_id != job_id:
                raise RuntimeError("Запрос исследования уже не активен")
            session.active_researcher = researcher
        try:
            result = researcher.research(
                question=question,
                environment=environment,
                required_facts=required_facts,
                repository_mcp=repository_mcp,
                provider_id=session.provider_id,
                model_id=session.model_id,
                variant=variant,
                cancel_event=session.cancel_event,
                on_event=research_event,
            )
            return {
                "summary": result.summary,
                "thinking": result.thinking,
                "opencode_seconds": result.opencode_seconds,
                "generation_seconds": result.generation_seconds,
                "evidence_only": True,
            }
        finally:
            with session.condition:
                if session.active_researcher is researcher:
                    session.active_researcher = None

    def draft(self, draft_id: str) -> dict[str, Any]:
        return self._drafts.require(draft_id).snapshot()

    def list_drafts(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for draft in self._drafts.list_all():
            try:
                form = self.container.forms.get_form(
                    draft.form_id, draft.environment
                )
                title = form.title
                current_version = form_version(form)
            except Exception:
                title = draft.form_id
                current_version = ""
            items.append({
                "id": draft.id,
                "form_id": draft.form_id,
                "title": title,
                "environment": draft.environment,
                "form_version": draft.form_version,
                "revision": draft.revision,
                "source": draft.source,
                "created_at": draft.created_at,
                "updated_at": draft.updated_at,
                "valid": draft.valid,
                "stale": not current_version or current_version != draft.form_version,
                "review_count": len(draft.fields),
            })
        return {"items": items}

    def save_draft(
        self,
        *,
        form_id: str,
        environment: str,
        form_version: str,
        values: Mapping[str, Any],
        draft_id: str = "",
        clear_review: bool = False,
        pending_review_fields: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        return self._drafts.save_values(
            form_id=form_id,
            environment=environment,
            version=form_version,
            values=values,
            draft_id=draft_id,
            clear_review=clear_review,
            pending_review_fields=pending_review_fields,
        ).snapshot()

    def delete_draft(self, draft_id: str) -> None:
        self._drafts.delete(draft_id)

    def refine_draft(
        self,
        draft_id: str,
        *,
        guidance: str,
        current_values: Mapping[str, Any],
        pending_fields: Sequence[str] = (),
    ) -> dict[str, Any]:
        draft = self._drafts.require(draft_id)
        session = self._session(draft.workflow_id)
        with session.condition:
            if session.busy:
                raise RuntimeError("Copilot уже выполняет другой запрос")
        draft = self._drafts.begin_refinement(
            draft_id,
            current_values=current_values,
            pending_fields=pending_fields,
        )
        snapshot = draft.snapshot()
        result = snapshot.get("result") or {}
        context = {
            "draft_id": draft.id,
            "form_id": draft.form_id,
            "environment": draft.environment,
            "form_version": draft.form_version,
            "current_values": copy_json(current_values),
            "previous_proposals": [
                copy_json(item)
                for item in result.get("fields") or []
                if not pending_fields or item.get("key") in pending_fields
            ],
        }
        try:
            started = self.start_message(
                draft.workflow_id,
                message=str(guidance),
                environment=draft.environment,
                ticket_id=None,
                provider_id=session.provider_id,
                model_id=session.model_id,
                thinking="auto",
                draft_context=context,
                refining_draft_id=draft.id,
            )
        except Exception as exc:
            self._drafts.fail(draft.id, str(exc))
            raise
        return {**draft.snapshot(), "job_id": started["job_id"]}

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
                "draft_id": job.draft_id,
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
            with self._lock:
                session = self._sessions.pop(session_id, None)
            if not session:
                continue
            if session.busy:
                session.copilot.cancel()
            session.copilot.detach()
            session.form_search.close()
            if session.active_researcher:
                session.active_researcher.cancel()
                session.active_researcher.close()
            self._drafts.delete_workflow(session.id)

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
            form = self.container.forms.get_form(
                handoff.form_id, job.environment
            )
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
            payload = self._validated_payload(result)
            persistent = self._drafts.save_ai_result(
                workflow_id=handoff.session_id,
                form_id=handoff.form_id,
                environment=job.environment,
                version=form_version(form),
                baseline=job.current_values,
                result=payload,
            )
            with job.lock:
                job.result = persistent.snapshot()["result"]
                job.draft_id = persistent.id
                job.status = "complete"
                job.progress = "Предложения готовы"
        except Exception as exc:
            _log.warning("web extractor failed job=%s error_type=%s", job.id, type(exc).__name__, exc_info=True)
            with job.lock:
                job.status = "cancelled" if job.cancel_event.is_set() else "error"
                job.error = "Операция отменена" if job.cancel_event.is_set() else str(exc)

    def _outcome_payload(self, session: WebCopilotSession, outcome: CopilotOutcome) -> dict[str, Any]:
        if session.copilot.mcp_native:
            job_id = session.job_id
            candidates = (
                session.turn_candidates
                if session.turn_candidates_job_id == job_id
                else []
            )
            draft_ids = (
                list(session.turn_draft_ids)
                if session.turn_draft_job_id == job_id
                else []
            )
            drafts = [
                draft
                for draft_id in draft_ids
                if (draft := self._drafts.get(draft_id)) is not None
            ]
            draft_items = [
                {
                    "draft_id": draft.id,
                    "form_id": draft.form_id,
                    "environment": draft.environment,
                    "valid": draft.valid,
                    "revision": draft.revision,
                }
                for draft in drafts
            ]
            single_draft = drafts[0] if len(drafts) == 1 else None
            return {
                "text": outcome.answer,
                "question": None,
                "intent": (
                    "execution_plan"
                    if len(drafts) > 1
                    else "single_form"
                    if single_draft is not None
                    else "clarification" if candidates else "conversation"
                ),
                "selected_form_id": single_draft.form_id if single_draft else None,
                "draft_id": single_draft.id if single_draft else None,
                "drafts": draft_items,
                "handoff_token": None,
                "form_candidates": [
                    {
                        "form_id": item.get("form_id"),
                        "title": item.get("title"),
                        "score": item.get("score"),
                        "reason": item.get("reason"),
                    }
                    for item in candidates
                ],
                "repository_items": [],
                "diagnostics": None,
                "plan": [],
                "warnings": [],
                "opencode_seconds": outcome.opencode_seconds,
                "generation_seconds": outcome.generation_seconds,
            }

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

    def _active_workflow(self, workflow_id: str) -> tuple[WebCopilotSession, str]:
        session = self._session(str(workflow_id))
        with session.condition:
            if not session.copilot.mcp_native:
                raise RuntimeError("Эта AI-сессия не поддерживает MCP workflow")
            if not session.busy or not session.job_id or session.cancel_event is None:
                raise RuntimeError("Для workflow сейчас нет активного Copilot-запроса")
            if session.cancel_event.is_set():
                raise RuntimeError("Copilot-запрос отменён")
            return session, session.job_id

    @staticmethod
    def _require_active_environment(
        session: WebCopilotSession,
        environment: str,
    ) -> None:
        if str(environment) != session.active_environment:
            raise ValueError(
                "MCP-вызов должен использовать окружение текущего запроса: "
                + session.active_environment
            )

    @staticmethod
    def _exact_variant(variants: Sequence[str], desired: str) -> str:
        mapping = {
            str(item).strip().casefold(): str(item).strip()
            for item in variants
            if str(item).strip()
        }
        return mapping.get(str(desired).casefold(), "")

    @classmethod
    def _best_variant(cls, variants: Sequence[str], desired: str) -> str:
        orders = {
            "xhigh": ("xhigh", "medium", "low", "none"),
            "medium": ("medium", "low", "none", "xhigh"),
            "low": ("low", "none", "medium", "xhigh"),
            "none": ("none", "low", "medium", "xhigh"),
        }
        for candidate in orders.get(desired, (desired, "low", "none")):
            value = cls._exact_variant(variants, candidate)
            if value:
                return value
        raise RuntimeError("У выбранной модели нет подходящего thinking variant")

    @staticmethod
    def _safe_detail(value: Any) -> str:
        try:
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            rendered = str(value)
        return redact_text(rendered)[:12000]

    def _session(self, session_id: str) -> WebCopilotSession:
        with self._lock:
            value = self._sessions.get(session_id)
        if value is None:
            self._restore_sessions_from_opencode()
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
