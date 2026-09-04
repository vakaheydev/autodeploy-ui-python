"""Управляемая многошаговая сессия form-extractor поверх OpenCodeClient."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from forms.base_form import BaseForm
from config.mcp_profiles import (
    choose_repository_mcp,
    repository_tool_allowlist,
    repository_tool_asklist,
)
from opencode_integration.client import (
    OpenCodeCancelled,
    OpenCodeClient,
    OpenCodeMessage,
)
from opencode_integration.context_builder import BuiltContext, ContextBuilder, redact_text
from opencode_integration.data_sources import AzureDevOpsDataSource, ITSMDataSource
from opencode_integration.manager import FORM_EXTRACTOR_AGENT
from opencode_integration.prompts import (
    SYSTEM_RULES,
    build_analysis_prompt,
    build_finalization_prompt,
)
from opencode_integration.reference_resolver import (
    DEFAULT_INLINE_REFERENCE_MAX_BYTES,
    DEFAULT_INLINE_REFERENCE_MAX_ITEMS,
    DEFAULT_INLINE_REFERENCE_TOTAL_BYTES,
    LocalReferenceResolver,
)
from opencode_integration.response_validator import ResponseValidator, ValidatedResponse
from opencode_integration.schemas import build_form_schema, describe_form

_log = logging.getLogger("opencode.agent")


@dataclass(frozen=True)
class ConversationEvent:
    kind: str
    title: str
    detail: str = ""
    permission_id: str = ""
    permission_name: str = ""


def _log_identifier(value: Any) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", "_", str(value))[:200]


class FormExtractorAgent:
    """Одна заявка → одна интерактивная session → validation → preview."""

    def __init__(
        self,
        client: OpenCodeClient,
        itsm_service: ITSMDataSource,
        tfs_service: AzureDevOpsDataSource,
        *,
        reference_resolver: Any,
        max_context_chars: int = 120_000,
        inline_reference_max_items: int = DEFAULT_INLINE_REFERENCE_MAX_ITEMS,
        inline_reference_max_bytes: int = DEFAULT_INLINE_REFERENCE_MAX_BYTES,
        inline_reference_total_bytes: int = DEFAULT_INLINE_REFERENCE_TOTAL_BYTES,
    ) -> None:
        self._client = client
        self._context_builder = ContextBuilder(
            itsm_service,
            tfs_service,
            max_context_chars=max_context_chars,
        )
        self._reference_resolver = LocalReferenceResolver(reference_resolver)
        self._inline_reference_max_items = inline_reference_max_items
        self._inline_reference_max_bytes = inline_reference_max_bytes
        self._inline_reference_total_bytes = inline_reference_total_bytes
        self._validator = ResponseValidator()
        self._session_id: Optional[str] = None
        self._cancel_event: Optional[threading.Event] = None
        self._form: Optional[BaseForm] = None
        self._ticket_id = ""
        self._environment = ""
        self._current_values: Mapping[str, Any] = {}
        self._provider_id = ""
        self._model_id = ""
        self._variant = ""
        self._context_warnings: list[str] = []
        self._on_progress: Callable[[str], None] = lambda _message: None
        self._on_event: Callable[[ConversationEvent], None] = lambda _event: None
        self._on_session: Callable[[Optional[str]], None] = lambda _session: None
        self._part_states: dict[str, str] = {}
        self._permission_ids: set[str] = set()
        self._last_session_status_signature = ""
        self._event_lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._started = 0.0
        self._pr_id: Optional[str] = None
        self._reference_values: dict[str, list[str]] = {}
        self._inline_reference_context: dict[str, dict[str, Any]] = {}
        self._inline_reference_values: dict[str, list[str]] = {}

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def reference_values(self) -> dict[str, list[str]]:
        return {key: list(values) for key, values in self._reference_values.items()}

    def begin(
        self,
        *,
        form: BaseForm,
        ticket_id: str,
        environment: str,
        current_values: Mapping[str, Any],
        allowed_mcp: Sequence[str] = (),
        repository_mcp: str = "",
        allow_repository_git_pull: bool = True,
        plan_guidance: str = "",
        provider_id: str = "",
        model_id: str = "",
        variant: str = "",
        cancel_event: Optional[threading.Event] = None,
        prepared_context: Optional[BuiltContext] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[ConversationEvent], None]] = None,
        on_session: Optional[Callable[[Optional[str]], None]] = None,
    ) -> OpenCodeMessage:
        with self._operation_lock:
            if self._session_id is not None:
                raise RuntimeError("OpenCode session уже создана")
            self._started = time.monotonic()
            self._form = form
            self._ticket_id = ticket_id.strip()
            self._environment = environment
            self._current_values = dict(current_values)
            self._provider_id = provider_id
            self._model_id = model_id
            self._variant = variant
            self._cancel_event = cancel_event
            self._on_progress = on_progress or (lambda _message: None)
            self._on_event = on_event or (lambda _event: None)
            self._on_session = on_session or (lambda _session: None)
            self._last_session_status_signature = ""

            if prepared_context is not None:
                if prepared_context.ticket_id != self._ticket_id:
                    raise ValueError(
                        "Подготовленный контекст относится к другой ITSM-заявке"
                    )
                self._on_progress(
                    "Использую уже подготовленный контекст…"
                    if self._ticket_id
                    else "Использую контекст AI-чата и MCP-источники…"
                )
                context = prepared_context
            else:
                try:
                    context = self._context_builder.build(
                        ticket_id=ticket_id,
                        environment=environment,
                        cancel_event=cancel_event,
                        on_progress=self._on_progress,
                    )
                except InterruptedError as exc:
                    raise OpenCodeCancelled("Операция отменена пользователем") from exc
            self._pr_id = context.pull_request_id
            self._ticket_id = context.ticket_id
            self._context_warnings = list(context.warnings)
            self._check_cancel()
            timeout = min(10.0, max(0.5, self._client.timeout))
            self._on_progress("Проверяю agent и provider…")
            self._client.require_agent(FORM_EXTRACTOR_AGENT, timeout=timeout)
            self._client.require_provider(provider_id, timeout=timeout)

            self._on_progress("Подготавливаю справочники формы…")
            inline_catalog = self._reference_resolver.build_inline_catalog(
                form=form,
                environment=environment,
                current_values=current_values,
                max_items=self._inline_reference_max_items,
                max_bytes=self._inline_reference_max_bytes,
                total_bytes=self._inline_reference_total_bytes,
                cancel_event=cancel_event,
                on_progress=self._on_progress,
            )
            self._inline_reference_context = inline_catalog.fields
            self._inline_reference_values = inline_catalog.reference_values

            enabled_mcp = self._available_mcp(allowed_mcp, timeout)
            active_repository_mcp = choose_repository_mcp(
                repository_mcp,
                enabled_mcp,
                {name: {"status": "connected"} for name in enabled_mcp},
            )
            self._check_cancel()
            self._session_id = self._client.create_session(
                (
                    f"AutoDeploy form assistant: {context.ticket_id}"
                    if context.ticket_id
                    else "AutoDeploy form assistant: chat request"
                ),
                agent=FORM_EXTRACTOR_AGENT,
                provider_id=provider_id,
                model_id=model_id,
                variant=variant,
                mcp_names=enabled_mcp,
                mcp_tool_allowlist=repository_tool_allowlist(active_repository_mcp),
                mcp_tool_asklist=repository_tool_asklist(
                    active_repository_mcp,
                    allow_git_pull=allow_repository_git_pull,
                ),
                metadata={
                    "source": "gravitee-autodeploy-ui",
                    "ticket_id": _log_identifier(context.ticket_id),
                    "form_id": form.form_id,
                },
            )
            self._on_session(self._session_id)
            self._emit(
                ConversationEvent(
                    "system",
                    "Сессия создана",
                    f"{self._session_id}; MCP: {', '.join(enabled_mcp) or 'нет'}",
                )
            )
            prompt = build_analysis_prompt(
                form_description=describe_form(
                    form,
                    environment,
                    reference_context=self._inline_reference_context,
                ),
                itsm_data=context.itsm,
                ado_data=context.ado,
                context_warnings=self._context_warnings,
                enabled_mcp=enabled_mcp,
                repository_mcp=active_repository_mcp,
                allow_repository_git_pull=allow_repository_git_pull,
                plan_guidance=plan_guidance,
            )
            self._on_progress("Агент анализирует данные для формы…")
            try:
                return self._client.send_chat_message(
                    session_id=self._session_id,
                    prompt=prompt,
                    system=SYSTEM_RULES,
                    agent=FORM_EXTRACTOR_AGENT,
                    provider_id=provider_id,
                    model_id=model_id,
                    variant=variant,
                    cancel_event=cancel_event,
                    on_event=self._handle_raw_event,
                )
            except OpenCodeCancelled:
                raise
            except Exception:
                self.close()
                raise

    def send_guidance(self, message: str) -> OpenCodeMessage:
        with self._operation_lock:
            session_id = self._require_session()
            text = redact_text(message.strip())
            if not text:
                raise ValueError("Введите уточнение для агента")
            if len(text) > 20_000:
                raise ValueError("Уточнение превышает 20000 символов")
            self._check_cancel()
            self._on_progress("OpenCode обрабатывает уточнение…")
            return self._client.send_chat_message(
                session_id=session_id,
                prompt=text,
                system=SYSTEM_RULES,
                agent=FORM_EXTRACTOR_AGENT,
                provider_id=self._provider_id,
                model_id=self._model_id,
                variant=self._variant,
                cancel_event=self._cancel_event,
                on_event=self._handle_raw_event,
            )

    def finalize(self) -> ValidatedResponse:
        with self._operation_lock:
            session_id = self._require_session()
            form = self._form
            assert form is not None
            self._check_cancel()
            semantic_schema = build_form_schema(
                form,
                self._inline_reference_values,
                strict_references=False,
            )
            self._on_progress("Формирую структурированные предложения…")
            structured = self._client.send_structured_message(
                session_id=session_id,
                prompt=build_finalization_prompt(),
                system=SYSTEM_RULES,
                schema=semantic_schema,
                agent=FORM_EXTRACTOR_AGENT,
                provider_id=self._provider_id,
                model_id=self._model_id,
                variant=self._variant,
                retry_count=2,
                cancel_event=self._cancel_event,
                on_event=self._handle_raw_event,
            )

            self._check_cancel()
            self._on_progress("Проверяю JSON по схеме…")
            # Первая проверка не применяет зависимости формы: reference labels
            # ещё не преобразованы в реальные ID.
            semantic = self._validator.validate(
                structured,
                form=form,
                current_values=self._current_values,
                schema=semantic_schema,
                check_domain=False,
            )
            self._on_progress("Сопоставляю значения со справочниками локально…")
            resolved = self._reference_resolver.resolve(
                semantic.payload,
                form=form,
                environment=self._environment,
                current_values=self._current_values,
                cancel_event=self._cancel_event,
                on_progress=self._on_progress,
            )
            self._reference_values = resolved.reference_values
            self._check_cancel()
            self._on_progress("Выполняю финальную Python-валидацию…")
            strict_schema = build_form_schema(
                form,
                resolved.reference_values,
                strict_references=True,
            )
            result = self._validator.validate(
                resolved.payload,
                form=form,
                current_values=self._current_values,
                reference_values=resolved.reference_values,
                schema=strict_schema,
                reference_candidates=resolved.candidates,
            )
            warnings = list(dict.fromkeys([
                *self._context_warnings,
                *resolved.warnings,
                *result.warnings,
            ]))
            final = ValidatedResponse(
                payload=result.payload,
                preview_fields=result.preview_fields,
                warnings=warnings,
                reference_candidates=result.reference_candidates,
            )
            self._on_progress("Готовлю preview…")
            _log.info(
                "autofill success ticket=%s pr=%s session=%s agent=%s model=%s "
                "duration=%.2fs filled=%d warnings=%d",
                _log_identifier(self._ticket_id),
                _log_identifier(self._pr_id or "none"),
                _log_identifier(session_id),
                FORM_EXTRACTOR_AGENT,
                _log_identifier(
                    f"{self._provider_id}/{self._model_id}"
                    if self._provider_id
                    else "opencode-default"
                ),
                time.monotonic() - self._started,
                sum(value is not None for value in final.form_data.values()),
                len(final.warnings),
            )
            return final

    def approve_permission(self, permission_id: str, *, allow: bool) -> None:
        session_id = self._require_session()
        self._client.respond_permission(
            session_id,
            permission_id,
            "once" if allow else "reject",
        )

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        session_id = self._session_id
        if session_id is not None:
            try:
                self._client.abort_session(session_id)
            except Exception:
                _log.warning(
                    "session abort failed id=%s",
                    _log_identifier(session_id),
                    exc_info=True,
                )

    def close(self) -> None:
        session_id = self._session_id
        self._session_id = None
        if session_id is not None:
            try:
                self._client.delete_session(session_id)
            except Exception:
                _log.warning(
                    "session delete failed id=%s",
                    _log_identifier(session_id),
                    exc_info=True,
                )
        self._on_session(None)

    def _available_mcp(self, requested: Sequence[str], timeout: float) -> list[str]:
        wanted = list(dict.fromkeys(name.strip() for name in requested if name.strip()))
        if not wanted:
            return []
        try:
            statuses = self._client.list_mcp_servers(timeout=timeout)
        except Exception as exc:
            self._context_warnings.append(
                f"Не удалось проверить MCP: {type(exc).__name__}"
            )
            return []
        enabled: list[str] = []
        for name in wanted:
            status = statuses.get(name, {})
            if status.get("status") == "connected":
                enabled.append(name)
            else:
                self._context_warnings.append(
                    f"MCP {name!r} недоступен: {status.get('status', 'not found')}"
                )
        return enabled

    def _handle_raw_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "event"))
        properties = event.get("properties")
        props = properties if isinstance(properties, dict) else {}

        if event_type == "client.sse.disconnected":
            self._emit(ConversationEvent(
                "warning",
                "Поток событий прерван",
                "Основной HTTP-запрос продолжает выполняться.",
            ))
            return
        if event_type in {"permission.asked", "permission.updated"}:
            permission_id = str(props.get("id") or props.get("permissionID") or "")
            if permission_id:
                with self._event_lock:
                    if permission_id in self._permission_ids:
                        return
                    self._permission_ids.add(permission_id)
            permission_name = str(props.get("permission") or props.get("tool") or "MCP tool")
            patterns = props.get("patterns", [])
            detail = self._safe_detail({
                "patterns": patterns,
                "metadata": props.get("metadata", {}),
            })
            self._emit(ConversationEvent(
                "permission",
                f"Требуется разрешение: {permission_name}",
                detail,
                permission_id=permission_id,
                permission_name=permission_name,
            ))
            return
        if event_type == "permission.replied":
            permission_id = str(props.get("requestID") or props.get("id") or "")
            if permission_id:
                with self._event_lock:
                    self._permission_ids.add(permission_id)
            reply = str(props.get("reply") or "processed")
            self._emit(ConversationEvent(
                "permission_resolved",
                "Permission request обработан",
                reply,
                permission_id=permission_id,
            ))
            return
        if event_type == "session.status":
            status = props.get("status")
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
                    "status", labels.get(status_type, f"OpenCode: {status_type}"), detail
                ))
            return
        if event_type in {"session.error", "session.failed"}:
            self._emit(ConversationEvent(
                "error",
                "Ошибка OpenCode session",
                self._safe_detail(props.get("error", props)),
            ))
            return
        if event_type == "message.part.updated":
            part = props.get("part")
            if not isinstance(part, dict) or part.get("type") != "tool":
                return
            part_id = str(part.get("id") or part.get("callID") or "")
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = str(state.get("status") or "updated")
            previous = self._part_states.get(part_id) if part_id else None
            if part_id:
                self._part_states[part_id] = status
            tool = str(part.get("tool") or state.get("title") or "MCP tool")
            if status == "pending":
                return
            if status == "completed" and previous in {"running", "completed"}:
                return
            if status == "error" and previous in {"running", "completed"}:
                self._emit(ConversationEvent(
                    "status",
                    f"Ошибка инструмента {tool}",
                    self._safe_detail(state.get("error", "")),
                ))
                return
            if previous == status:
                return
            detail_value = (
                state.get("error")
                if status == "error"
                else state.get("input", "")
            )
            self._emit(ConversationEvent(
                "tool" if status != "error" else "error",
                tool,
                self._safe_detail(detail_value),
            ))

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
                "event kind=status title=%s detail=%s",
                event.title,
                event.detail or "none",
            )
        else:
            _log.info("event kind=%s title=%s", event.kind, event.title)
        try:
            self._on_event(event)
        except Exception:
            _log.exception("conversation event callback failed")

    def _require_session(self) -> str:
        if self._session_id is None:
            raise RuntimeError("OpenCode session ещё не создана или уже закрыта")
        return self._session_id

    def _check_cancel(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
