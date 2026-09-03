"""Высокоуровневый form-extractor workflow поверх OpenCodeClient."""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Optional

from forms.base_form import BaseForm
from opencode_integration.client import OpenCodeCancelled, OpenCodeClient
from opencode_integration.context_builder import ContextBuilder
from opencode_integration.manager import FORM_EXTRACTOR_AGENT
from opencode_integration.prompts import SYSTEM_RULES, build_extraction_prompt
from opencode_integration.response_validator import ResponseValidator, ValidatedResponse
from opencode_integration.schemas import build_form_schema, describe_form

_log = logging.getLogger(__name__)


def _log_identifier(value: Any) -> str:
    """Оставляет в audit log только короткий однострочный идентификатор."""
    return re.sub(r"[\x00-\x1f\x7f]+", "_", str(value))[:200]


class FormExtractorAgent:
    """Одна заявка → одна session → structured output → Python validation."""

    def __init__(
        self,
        client: OpenCodeClient,
        itsm_service: Any,
        tfs_service: Any,
        *,
        max_context_chars: int = 120_000,
    ) -> None:
        self._client = client
        self._context_builder = ContextBuilder(
            itsm_service,
            tfs_service,
            max_context_chars=max_context_chars,
        )
        self._validator = ResponseValidator()

    def extract(
        self,
        *,
        form: BaseForm,
        ticket_id: str,
        environment: str,
        current_values: Mapping[str, Any],
        reference_data: Any,
        reference_values: Mapping[str, Iterable[Any]],
        provider_id: str = "",
        model_id: str = "",
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_session: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ValidatedResponse:
        started = time.monotonic()
        notify = on_progress or (lambda _message: None)
        session_id: Optional[str] = None
        pr_id: Optional[str] = None
        validation_status = "not_started"
        try:
            context = self._context_builder.build(
                ticket_id=ticket_id,
                environment=environment,
                reference_data=reference_data,
                cancel_event=cancel_event,
                on_progress=notify,
            )
            pr_id = context.pull_request_id
            self._check_cancel(cancel_event)

            # Проверка повторяется перед каждым запросом, даже после startup check.
            metadata_timeout = min(10.0, max(0.5, self._client.timeout))
            self._client.require_agent(FORM_EXTRACTOR_AGENT, timeout=metadata_timeout)
            self._client.require_provider(provider_id, timeout=metadata_timeout)
            schema = build_form_schema(form, reference_values)
            prompt = build_extraction_prompt(
                form_description=describe_form(form, environment),
                itsm_data=context.itsm,
                ado_data=context.ado,
                reference_data=context.references,
                context_warnings=context.warnings,
            )

            session_id = self._client.create_session(
                f"AutoDeploy form extraction: {ticket_id}"
            )
            if on_session is not None:
                on_session(session_id)
            self._check_cancel(cancel_event)

            notify("Анализирую данные...")
            structured = self._client.send_structured_message(
                session_id=session_id,
                prompt=prompt,
                system=SYSTEM_RULES,
                schema=schema,
                agent=FORM_EXTRACTOR_AGENT,
                provider_id=provider_id,
                model_id=model_id,
                retry_count=2,
                cancel_event=cancel_event,
                on_event=lambda event: self._report_event(event, notify),
            )

            self._check_cancel(cancel_event)
            notify("Проверяю ответ...")
            result = self._validator.validate(
                structured,
                form=form,
                current_values=current_values,
                reference_values=reference_values,
                schema=schema,
            )
            # Системные предупреждения сбора показываются независимо от того,
            # повторила ли их модель в meta.warnings.
            result = ValidatedResponse(
                payload=result.payload,
                preview_fields=result.preview_fields,
                warnings=list(dict.fromkeys([*context.warnings, *result.warnings])),
            )
            self._check_cancel(cancel_event)
            validation_status = "valid"
            notify("Готовлю preview...")
            _log.info(
                "AI autofill success ticket=%s pr=%s session=%s agent=%s model=%s "
                "duration=%.2fs validation=%s filled=%d warnings=%d",
                _log_identifier(ticket_id),
                _log_identifier(pr_id or "none"),
                _log_identifier(session_id),
                FORM_EXTRACTOR_AGENT,
                _log_identifier(
                    f"{provider_id}/{model_id}" if provider_id else "opencode-default"
                ),
                time.monotonic() - started,
                validation_status,
                sum(value is not None for value in result.form_data.values()),
                len(result.warnings),
            )
            return result
        except InterruptedError as exc:
            raise OpenCodeCancelled(str(exc)) from exc
        except Exception as exc:
            cancelled = cancel_event is not None and cancel_event.is_set()
            _log.warning(
                "AI autofill failed ticket=%s pr=%s session=%s agent=%s "
                "duration=%.2fs validation=%s error_type=%s",
                _log_identifier(ticket_id),
                _log_identifier(pr_id or "none"),
                _log_identifier(session_id or "none"),
                FORM_EXTRACTOR_AGENT,
                time.monotonic() - started,
                validation_status,
                OpenCodeCancelled.__name__ if cancelled else type(exc).__name__,
            )
            if cancelled and not isinstance(exc, OpenCodeCancelled):
                raise OpenCodeCancelled("Операция отменена пользователем") from exc
            raise
        finally:
            if session_id is not None:
                try:
                    self._client.delete_session(session_id)
                except Exception as exc:
                    _log.warning(
                        "Could not delete OpenCode session=%s error_type=%s",
                        _log_identifier(session_id),
                        type(exc).__name__,
                    )
            if on_session is not None:
                on_session(None)

    @staticmethod
    def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")

    @staticmethod
    def _report_event(event: dict[str, Any], notify: Callable[[str], None]) -> None:
        """SSE влияет только на статус, никогда — на данные preview."""
        event_type = event.get("type")
        properties = event.get("properties", {})
        if event_type == "client.sse.disconnected":
            notify("Поток прогресса прерван; ожидаю итоговый ответ...")
            return
        if event_type == "session.status" and isinstance(properties, dict):
            status = properties.get("status", {})
            if isinstance(status, dict) and status.get("type") == "retry":
                attempt = status.get("attempt", "?")
                notify(f"OpenCode повторяет запрос (попытка {attempt})...")
            elif isinstance(status, dict) and status.get("type") == "busy":
                notify("Анализирую данные...")
