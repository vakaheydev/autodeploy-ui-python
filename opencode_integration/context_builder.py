"""Получение, нормализация и очистка недоверенного ITSM/ADO-контекста."""
from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional

from opencode_integration.data_sources import (
    AzureDevOpsDataSource,
    DataSourceNotConfiguredError,
    ITSMAIPrompt,
    ITSMAIPromptRequest,
    ITSMDataSource,
)
from opencode_integration.request_loader import sanitize_request


DEFAULT_MAX_CONTEXT_CHARS = 120_000
HARD_MAX_CONTEXT_CHARS = 500_000
MAX_STRING_CHARS = 20_000
MAX_COLLECTION_ITEMS = 200
MAX_DEPTH = 12
MAX_ITSM_AI_INSTRUCTIONS_CHARS = 16_000
MAX_ITSM_TICKET_TYPE_CHARS = 200

_SECRET_KEY_RE = re.compile(
    r"(?:^|[_\-.])(api[_-]?key|access[_-]?key(?:[_-]?id)?|secret[_-]?key|token|"
    r"refresh[_-]?token|sas[_-]?token|pat|password|passwd|pwd|secret|"
    r"client[_-]?secret|credential|credentials|connection[_-]?string|authorization|"
    r"auth[_-]?header|private[_-]?key|cookie|set[_-]?cookie)(?:$|[_\-.])",
    re.IGNORECASE,
)
_PEM_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_AUTH_RE = re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/._~=-]{8,}", re.IGNORECASE)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z0-9_.-]*(?:api[_-]?key|access[_-]?key|secret[_-]?key|token|pat|"
    r"password|passwd|client[_-]?secret|connection[_-]?string|authorization|"
    r"private[_-]?key|cookie)[a-z0-9_.-]*)"
    r"\b[\"']?\s*[:=]\s*[\"']?([^\"'\s,;}]{6,})"
)
_ADO_PR_URL_RE = re.compile(
    r"https?://[^\s<>\"']+/(?:pullrequest|pullrequests?)/\d+[^\s<>\"']*",
    re.IGNORECASE,
)
_TECHNICAL_KEYS = {
    "headers", "requestheaders", "responseheaders", "httpheaders",
    "environmentvariables", "environmentvars", "processenvironment", "osenviron",
    "rawrequest", "rawresponse", "stacktrace", "debugdump", "binarycontent",
}


class ContextBuildError(RuntimeError):
    """Контекст нельзя безопасно подготовить для извлечения."""


@dataclass(frozen=True)
class BuiltContext:
    ticket_id: str
    itsm: Any
    ado: Any
    warnings: list[str] = field(default_factory=list)
    pull_request_id: Optional[str] = None
    ticket_type: str = ""
    ai_instructions: str = ""


def is_secret_key(key: str) -> bool:
    normalized = key.replace(" ", "_")
    if _SECRET_KEY_RE.search(normalized):
        return True
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return (
        compact in {"pat", "authorization", "password", "passwd", "pwd", "cookie"}
        or compact.endswith((
            "apikey", "accesskey", "accesskeyid", "secretkey", "accesstoken",
            "refreshtoken", "sastoken", "clientsecret", "privatekey",
            "credential", "credentials", "connectionstring",
        ))
        or compact.endswith("token")
        or compact.endswith("secret")
        or compact.endswith("password")
    )


def is_unneeded_technical_key(key: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return compact in _TECHNICAL_KEYS


def redact_text(value: str) -> str:
    """Удаляет распространённые секреты, сохраняя полезный окружающий текст."""
    value = _PEM_RE.sub("[REDACTED_PRIVATE_KEY]", value)
    value = _AUTH_RE.sub("[REDACTED_AUTHORIZATION]", value)
    value = _JWT_RE.sub("[REDACTED_JWT]", value)
    value = _ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
    return value


def sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Приводит произвольный ответ API к JSON-совместимому очищенному объекту."""
    if key and is_secret_key(key):
        return "[REDACTED]"
    if key and is_unneeded_technical_key(key):
        return "[REMOVED_TECHNICAL_DATA]"
    if depth >= MAX_DEPTH:
        return "[TRUNCATED_MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).replace("\x00", "")
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = redact_text(normalized)
        if len(normalized) > MAX_STRING_CHARS:
            return normalized[:MAX_STRING_CHARS] + "\n[TRUNCATED]"
        return normalized
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, (child_key, child_value) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                result["_truncated_items"] = len(value) - index
                break
            safe_key = str(child_key)[:300]
            result[safe_key] = sanitize(child_value, key=safe_key, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [sanitize(item, depth=depth + 1) for item in items[:MAX_COLLECTION_ITEMS]]
        if len(items) > MAX_COLLECTION_ITEMS:
            result.append({"_truncated_items": len(items) - MAX_COLLECTION_ITEMS})
        return result
    return sanitize(str(value), key=key, depth=depth + 1)


def resolve_itsm_ai_prompt(
    itsm_service: Any,
    *,
    ticket_id: str,
    environment: str,
    ticket_context: Any,
    form_id: str = "",
    prompt_override: Optional[Callable[[str], Optional[str]]] = None,
) -> Optional[ITSMAIPrompt]:
    """Resolve optional trusted corporate guidance for one sanitized ticket.

    The capability is deliberately discovered with ``getattr`` so pre-existing
    corporate adapters that only implement ``get_ticket`` remain compatible.
    The hook result is bounded and secret-redacted before it reaches OpenCode.
    """
    hook = getattr(itsm_service, "get_ai_prompt", None)
    if not callable(hook):
        return None
    result = hook(ITSMAIPromptRequest(
        ticket_id=str(ticket_id).strip(),
        environment=str(environment).strip(),
        ticket_context=copy.deepcopy(ticket_context),
        form_id=str(form_id).strip(),
    ))
    if result is None:
        return None
    if not isinstance(result, ITSMAIPrompt):
        raise TypeError(
            "ITSMService.get_ai_prompt должен вернуть ITSMAIPrompt или None"
        )
    if not isinstance(result.ticket_type, str):
        raise TypeError("ITSMAIPrompt.ticket_type должен быть строкой")
    if not isinstance(result.instructions, str):
        raise TypeError("ITSMAIPrompt.instructions должен быть строкой")

    ticket_type = unicodedata.normalize("NFKC", result.ticket_type)
    ticket_type = redact_text(ticket_type.replace("\x00", "")).strip()
    instructions_source = result.instructions
    if prompt_override is not None and ticket_type:
        configured = prompt_override(ticket_type)
        if configured is not None:
            if not isinstance(configured, str):
                raise TypeError("Настроенный ITSM AI prompt должен быть строкой")
            instructions_source = configured
    instructions = unicodedata.normalize("NFKC", instructions_source)
    instructions = redact_text(
        instructions.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    if not ticket_type and not instructions:
        return None
    if instructions and not ticket_type:
        raise ValueError(
            "ITSMAIPrompt.ticket_type обязателен, если заданы instructions"
        )
    if len(ticket_type) > MAX_ITSM_TICKET_TYPE_CHARS:
        raise ValueError(
            f"ITSMAIPrompt.ticket_type превышает {MAX_ITSM_TICKET_TYPE_CHARS} символов"
        )
    if len(instructions) > MAX_ITSM_AI_INSTRUCTIONS_CHARS:
        raise ValueError(
            "ITSMAIPrompt.instructions превышает "
            f"{MAX_ITSM_AI_INSTRUCTIONS_CHARS} символов"
        )
    return ITSMAIPrompt(ticket_type=ticket_type, instructions=instructions)


def _fit_to_budget(value: Any, max_chars: int) -> Any:
    rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return value
    excerpt_size = max(0, max_chars - 120)
    return {
        "_truncated": True,
        "_original_characters": len(rendered),
        "_json_excerpt": rendered[:excerpt_size],
    }


def fit_context_to_budget(value: Any, max_chars: int) -> Any:
    """Bound already-sanitized JSON context without exposing private helpers."""
    limit = min(HARD_MAX_CONTEXT_CHARS, max(1_000, int(max_chars)))
    return _fit_to_budget(value, limit)


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + (str(key),)
            yield child_path, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + (str(index),))


def find_pull_request_reference(itsm_data: Any) -> Any:
    """Ищет явную ссылку/ID связанного PR без доменных предположений."""
    id_candidates: list[Any] = []
    for path, value in _walk(itsm_data):
        key = path[-1].lower().replace("-", "_") if path else ""
        if isinstance(value, str):
            match = _ADO_PR_URL_RE.search(value)
            if match:
                return match.group(0).rstrip(".,);]")
        if key in {
            "pull_request", "pullrequest", "pull_request_url", "pullrequesturl",
            "pr_url", "ado_pr_url", "merge_request_url",
        } and value not in (None, ""):
            if isinstance(value, dict):
                return value
            text = str(value).strip()
            match = _ADO_PR_URL_RE.search(text)
            return match.group(0).rstrip(".,);]") if match else text
        if key in {"pull_request_id", "pullrequestid", "pr_id", "prid"}:
            id_candidates.append(value)
    return id_candidates[0] if id_candidates else None


def pull_request_id(reference: Any, ado_data: Any = None) -> Optional[str]:
    for candidate in (ado_data, reference):
        if isinstance(candidate, dict):
            for key in ("pullRequestId", "pull_request_id"):
                value = candidate.get(key)
                if value is not None:
                    return str(value)
            nested = candidate.get("pull_request") or candidate.get("pullRequest")
            if isinstance(nested, dict):
                nested_id = pull_request_id(nested)
                if nested_id is not None:
                    return nested_id
            if candidate.get("id") is not None and candidate is reference:
                return str(candidate["id"])
        if candidate is not None:
            text = str(candidate).strip()
            if text.isdigit():
                return text
            match = re.search(r"/pullrequests?/(\d+)(?:[/?#]|$)", text, re.IGNORECASE)
            if match:
                return match.group(1)
    return None


class ContextBuilder:
    """Оркестрирует ITSM/ADO-клиенты и выдаёт только очищенный контекст."""

    def __init__(
        self,
        itsm_service: ITSMDataSource,
        tfs_service: AzureDevOpsDataSource,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        prompt_override: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._itsm_service = itsm_service
        self._tfs_service = tfs_service
        self._max_context_chars = min(
            HARD_MAX_CONTEXT_CHARS,
            max(10_000, int(max_context_chars)),
        )
        self._prompt_override = prompt_override

    def build(
        self,
        *,
        ticket_id: str,
        environment: str,
        cancel_event: Any = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> BuiltContext:
        notify = on_progress or (lambda _message: None)
        clean_ticket_id = str(ticket_id).strip()
        if not clean_ticket_id:
            raise ContextBuildError("Не указан ID ITSM-заявки")
        if len(clean_ticket_id) > 200:
            raise ContextBuildError("ID ITSM-заявки превышает 200 символов")
        if any(ord(char) < 32 or ord(char) == 127 for char in clean_ticket_id):
            raise ContextBuildError("ID ITSM-заявки содержит управляющие символы")
        self._check_cancel(cancel_event)
        notify("Получаю заявку...")
        try:
            raw_itsm = sanitize_request(
                self._itsm_service,
                clean_ticket_id,
                environment,
            )
        except DataSourceNotConfiguredError as exc:
            # Это контролируемая локальная ошибка адаптера, а не потенциально
            # чувствительный ответ корпоративной ITSM.
            raise ContextBuildError(str(exc)) from exc
        except Exception as exc:
            status = getattr(exc, "status", None)
            status_note = f" (HTTP {status})" if isinstance(status, int) else ""
            # Не пробрасываем body ITSM-ошибки в UI/логи: он может содержать PII.
            raise ContextBuildError(
                f"Не удалось получить ITSM-заявку{status_note}: {type(exc).__name__}"
            ) from exc
        if not raw_itsm:
            raise ContextBuildError("ITSM вернул пустые данные заявки")

        self._check_cancel(cancel_event)
        pr_reference = find_pull_request_reference(raw_itsm)
        raw_ado: Any = {}
        warnings: list[str] = []
        if pr_reference is None:
            warnings.append("В заявке не найдена явная ссылка или ID Azure DevOps PR")
        else:
            notify("Получаю данные PR...")
            try:
                raw_ado = self._tfs_service.get_pull_request(pr_reference, environment)
                if not raw_ado:
                    warnings.append("Azure DevOps вернул пустые данные PR")
            except DataSourceNotConfiguredError as exc:
                warnings.append(str(exc))
            except Exception as exc:
                # ITSM-контекст всё ещё полезен; ошибка ADO явно попадёт в preview.
                warnings.append(f"Не удалось получить Azure DevOps PR: {type(exc).__name__}")

        self._check_cancel(cancel_event)
        notify("Подготавливаю контекст...")
        clean_itsm = sanitize(raw_itsm)
        clean_ado = sanitize(raw_ado)

        try:
            ai_prompt = resolve_itsm_ai_prompt(
                self._itsm_service,
                ticket_id=clean_ticket_id,
                environment=environment,
                ticket_context=clean_itsm,
                prompt_override=self._prompt_override,
            )
        except Exception as exc:
            # The private hook is trusted code, but its exception/body may still
            # contain corporate data and therefore must not be reflected to UI.
            raise ContextBuildError(
                "Не удалось выбрать корпоративные AI-инструкции для заявки: "
                f"{type(exc).__name__}"
            ) from exc

        # Справочники сюда принципиально не входят: модель возвращает смысловые
        # кандидаты, а идентификаторы сопоставляются локальным Python-кодом.
        clean_itsm = _fit_to_budget(clean_itsm, int(self._max_context_chars * 0.53))
        clean_ado = _fit_to_budget(clean_ado, int(self._max_context_chars * 0.47))

        return BuiltContext(
            ticket_id=clean_ticket_id,
            itsm=clean_itsm,
            ado=clean_ado,
            warnings=warnings,
            pull_request_id=pull_request_id(pr_reference, raw_ado),
            ticket_type=ai_prompt.ticket_type if ai_prompt else "",
            ai_instructions=ai_prompt.instructions if ai_prompt else "",
        )

    @staticmethod
    def _check_cancel(cancel_event: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Операция отменена пользователем")
