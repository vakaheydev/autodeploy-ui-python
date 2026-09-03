"""HTTP/SSE-клиент OpenCode Server 1.18.18 для общего localhost-сервера."""
from __future__ import annotations

import base64
import json
import logging
import math
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence

from opencode_integration.context_builder import redact_text

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_SSE_EVENT_BYTES = 512 * 1024
_log = logging.getLogger("opencode.http")
_MCP_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_READ_ONLY_TOOL_MARKERS = (
    "get", "list", "read", "search", "find", "query", "fetch", "lookup",
    "describe", "show", "inspect", "status", "resolve",
)
_MUTATING_TOOL_MARKERS = (
    "create", "add", "update", "edit", "delete", "remove", "write", "set",
    "put", "post", "patch", "approve", "merge", "close", "reopen", "deploy",
    "rollback", "run", "trigger", "queue", "execute", "start", "stop",
    "cancel", "abort", "send", "publish", "upload", "assign", "link",
)


class OpenCodeError(RuntimeError):
    """Базовая безопасная ошибка интеграции."""


class OpenCodeHttpError(OpenCodeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        if status == 401:
            message = "неверные credentials OpenCode Server"
        super().__init__(f"OpenCode HTTP {status}: {redact_text(message)[:2000]}")


class OpenCodeStructuredOutputError(OpenCodeError):
    """Модель не смогла сформировать structured output."""


class OpenCodeAgentMissingError(OpenCodeError):
    """Специализированный агент не загружен сервером."""


class OpenCodeProviderError(OpenCodeError):
    """Provider/model не настроен в OpenCode."""


class OpenCodeCancelled(OpenCodeError):
    """Операция отменена пользователем."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Не даёт localhost-серверу перенаправить чувствительный prompt наружу."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class OpenCodeHealth:
    healthy: bool
    version: str


@dataclass(frozen=True)
class OpenCodeMessage:
    """Завершённое сообщение ассистента без предположений о UI."""

    text: str
    info: Dict[str, Any]
    parts: tuple[Dict[str, Any], ...]


def _unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value and set(value).intersection({"data", "error"}):
        return value["data"]
    return value


def build_session_permissions(
    mcp_names: Sequence[str],
    tool_allowlist: Optional[Mapping[str, Sequence[str]]] = None,
    tool_asklist: Optional[Mapping[str, Sequence[str]]] = None,
) -> list[Dict[str, str]]:
    """Deny-by-default; известный read-only профиль разрешается точно."""
    rules: list[Dict[str, str]] = [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "StructuredOutput", "pattern": "*", "action": "allow"},
    ]
    names = {item.strip() for item in mcp_names if item.strip()}
    invalid = sorted(name for name in names if not _MCP_NAME_RE.fullmatch(name))
    if invalid:
        raise ValueError(
            "Некорректное имя MCP; разрешены A-Z, a-z, 0-9, '.', '_' и '-': "
            + ", ".join(invalid)
        )
    exact = tool_allowlist or {}
    confirm = tool_asklist or {}
    for name in sorted(names):
        if name in exact or name in confirm:
            for tool in dict.fromkeys(
                str(item).strip() for item in exact.get(name, ())
            ):
                if not _MCP_NAME_RE.fullmatch(tool):
                    raise ValueError(f"Некорректное имя MCP tool: {tool!r}")
                rules.append({
                    "permission": f"{name}_{tool}",
                    "pattern": "*",
                    "action": "allow",
                })
            for tool in dict.fromkeys(str(item).strip() for item in confirm.get(name, ())):
                if not _MCP_NAME_RE.fullmatch(tool):
                    raise ValueError(f"Некорректное имя MCP tool: {tool!r}")
                rules.append({
                    "permission": f"{name}_{tool}",
                    "pattern": "*",
                    "action": "ask",
                })
            # При наличии профиля никакие эвристические wildcard-разрешения
            # для этого сервера не добавляются.
            continue
        # OpenCode именует MCP tools как <server>_<tool>. Разрешаем запросить
        # согласие только для явно read-oriented имён. Неизвестные операции
        # остаются под общим deny. Мутационные маркеры идут последними и потому
        # перекрывают, например, двусмысленное execute_query.
        for marker in _READ_ONLY_TOOL_MARKERS:
            for tool_pattern in (f"{name}_{marker}*", f"{name}_*_{marker}*"):
                rules.append({
                    "permission": tool_pattern,
                    "pattern": "*",
                    "action": "ask",
                })
        for marker in _MUTATING_TOOL_MARKERS:
            for tool_pattern in (f"{name}_{marker}*", f"{name}_*_{marker}*"):
                rules.append({
                    "permission": tool_pattern,
                    "pattern": "*",
                    "action": "deny",
                })
    return rules


class OpenCodeClient:
    """Клиент общего сервера с auth и жёстко закреплённой runtime-директорией."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        *,
        directory: Path | str | None = None,
        username: str = "opencode",
        password: str = "",
    ) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "OpenCode Server разрешён только по адресу http://127.0.0.1:<port>"
            )
        if parsed.port is None or not 1 <= parsed.port <= 65535:
            raise ValueError("В адресе OpenCode Server должен быть корректный порт")
        if not math.isfinite(float(timeout)) or timeout <= 0:
            raise ValueError("OpenCode timeout должен быть положительным")
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.directory = str(Path(directory).resolve()) if directory else ""
        self.username = username.strip() or "opencode"
        self._password = password
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def health(self, timeout: Optional[float] = None) -> OpenCodeHealth:
        payload = _unwrap_data(
            self._request("GET", "/global/health", timeout=timeout, instance=False)
        )
        if not isinstance(payload, dict):
            raise OpenCodeError("Некорректный ответ /global/health")
        return OpenCodeHealth(
            healthy=payload.get("healthy") is True,
            version=str(payload.get("version", "")),
        )

    def list_agents(self, timeout: Optional[float] = None) -> list[Dict[str, Any]]:
        payload = _unwrap_data(self._request("GET", "/agent", timeout=timeout))
        if not isinstance(payload, list):
            raise OpenCodeError("Некорректный ответ /agent")
        return [item for item in payload if isinstance(item, dict)]

    def require_agent(self, agent_name: str, timeout: Optional[float] = None) -> None:
        for agent in self.list_agents(timeout=timeout):
            if agent.get("name") != agent_name and agent.get("id") != agent_name:
                continue
            if agent.get("mode") not in (None, "primary"):
                raise OpenCodeAgentMissingError(
                    f"Агент {agent_name!r} загружен не как primary"
                )
            return
        raise OpenCodeAgentMissingError(
            f"OpenCode не загрузил обязательного агента {agent_name!r} "
            f"для runtime-директории формы"
        )

    def has_agent(self, agent_name: str, timeout: Optional[float] = None) -> bool:
        try:
            self.require_agent(agent_name, timeout=timeout)
        except OpenCodeAgentMissingError:
            return False
        return True

    def provider_status(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        payload = _unwrap_data(self._request("GET", "/provider", timeout=timeout))
        if not isinstance(payload, dict):
            raise OpenCodeError("Некорректный ответ /provider")
        return payload

    def require_provider(
        self,
        provider_id: str = "",
        timeout: Optional[float] = None,
    ) -> None:
        status = self.provider_status(timeout=timeout)
        connected = status.get("connected", [])
        if not isinstance(connected, list):
            connected = []
        if provider_id and provider_id not in connected:
            raise OpenCodeProviderError(
                f"Provider {provider_id!r} не подключён в OpenCode"
            )
        if not provider_id and not connected:
            raise OpenCodeProviderError(
                "В OpenCode не настроен ни один provider/API key"
            )

    def list_mcp_servers(self, timeout: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        payload = _unwrap_data(self._request("GET", "/mcp", timeout=timeout))
        if not isinstance(payload, dict):
            raise OpenCodeError("Некорректный ответ /mcp")
        return {
            str(name): dict(status)
            for name, status in payload.items()
            if isinstance(status, dict)
        }

    def list_pending_permissions(
        self,
        timeout: Optional[float] = None,
        *,
        quiet: bool = False,
    ) -> list[Dict[str, Any]]:
        """Возвращает pending permissions; используется как fallback при обрыве SSE."""
        payload = _unwrap_data(
            self._request("GET", "/permission", timeout=timeout, quiet=quiet)
        )
        if not isinstance(payload, list):
            raise OpenCodeError("Некорректный ответ /permission")
        return [item for item in payload if isinstance(item, dict)]

    def create_session(
        self,
        title: str,
        *,
        agent: str = "",
        provider_id: str = "",
        model_id: str = "",
        mcp_names: Sequence[str] = (),
        mcp_tool_allowlist: Optional[Mapping[str, Sequence[str]]] = None,
        mcp_tool_asklist: Optional[Mapping[str, Sequence[str]]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> str:
        if bool(provider_id) != bool(model_id):
            raise OpenCodeProviderError(
                "Для явного выбора модели нужны оба значения: provider ID и model ID"
            )
        body: Dict[str, Any] = {
            "title": title[:200],
            "permission": build_session_permissions(
                mcp_names,
                mcp_tool_allowlist,
                mcp_tool_asklist,
            ),
            "metadata": dict(metadata or {}),
        }
        if agent:
            body["agent"] = agent
        if provider_id and model_id:
            # В CreateInput OpenCode 1.18.18 поле модели называется `id`.
            # В PromptInput ниже контракт другой: там используется `modelID`.
            body["model"] = {"providerID": provider_id, "id": model_id}
        payload = _unwrap_data(self._request("POST", "/session", body))
        if not isinstance(payload, dict) or not payload.get("id"):
            raise OpenCodeError("OpenCode не вернул ID созданной session")
        session_id = str(payload["id"])
        _log.info("session created id=%s agent=%s mcp_count=%d", session_id, agent, len(mcp_names))
        return session_id

    def delete_session(self, session_id: str) -> None:
        self._request(
            "DELETE",
            f"/session/{urllib.parse.quote(session_id, safe='')}",
            timeout=min(5.0, max(0.5, self.timeout)),
        )
        _log.info("session deleted id=%s", session_id)

    def abort_session(self, session_id: str) -> None:
        self._request(
            "POST",
            f"/session/{urllib.parse.quote(session_id, safe='')}/abort",
            timeout=min(5.0, max(0.5, self.timeout)),
        )
        _log.info("session aborted id=%s", session_id)

    def respond_permission(
        self,
        session_id: str,
        permission_id: str,
        response: str,
    ) -> None:
        if response not in {"once", "always", "reject"}:
            raise ValueError("Некорректный ответ на permission request")
        # Используем актуальный endpoint 1.18.18. Старый session-scoped endpoint
        # всё ещё существует, но помечен в OpenAPI как deprecated.
        path = (
            f"/permission/{urllib.parse.quote(permission_id, safe='')}/reply"
        )
        self._request("POST", path, {"reply": response})
        _log.info(
            "permission response session=%s permission_id=%s response=%s",
            session_id,
            permission_id,
            response,
        )

    def send_chat_message(
        self,
        *,
        session_id: str,
        prompt: str,
        system: str = "",
        agent: str,
        provider_id: str = "",
        model_id: str = "",
        cancel_event: Optional[threading.Event] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> OpenCodeMessage:
        body = self._message_body(
            prompt=prompt,
            system=system,
            agent=agent,
            provider_id=provider_id,
            model_id=model_id,
        )
        response = self._send_message(
            session_id=session_id,
            body=body,
            cancel_event=cancel_event,
            on_event=on_event,
        )
        parts = tuple(
            item for item in response.get("parts", []) if isinstance(item, dict)
        )
        texts = [
            str(item.get("text", ""))
            for item in parts
            if item.get("type") == "text" and item.get("text")
        ]
        return OpenCodeMessage(
            text="\n".join(texts).strip(),
            info=dict(response.get("info") or {}),
            parts=parts,
        )

    def send_structured_message(
        self,
        *,
        session_id: str,
        prompt: str,
        system: str,
        schema: Dict[str, Any],
        agent: str,
        provider_id: str = "",
        model_id: str = "",
        retry_count: int = 2,
        cancel_event: Optional[threading.Event] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_response: Optional[Callable[[Mapping[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        body = self._message_body(
            prompt=prompt,
            system=system,
            agent=agent,
            provider_id=provider_id,
            model_id=model_id,
        )
        body["format"] = {
            "type": "json_schema",
            "schema": schema,
            "retryCount": max(0, int(retry_count)),
        }
        response = self._send_message(
            session_id=session_id,
            body=body,
            cancel_event=cancel_event,
            on_event=on_event,
        )
        if on_response is not None:
            try:
                on_response(response)
            except Exception:
                _log.warning("structured response observer failed", exc_info=True)
        info = response.get("info") or {}
        structured = None
        for container in (info, response):
            if not isinstance(container, dict):
                continue
            for key in ("structured", "structured_output", "structuredOutput"):
                if key in container:
                    structured = container[key]
                    break
            if structured is not None:
                break
        if structured is None:
            raise OpenCodeStructuredOutputError(
                "OpenCode завершил запрос без обязательного structured_output"
            )
        if not isinstance(structured, dict):
            raise OpenCodeStructuredOutputError(
                "structured_output имеет неожиданный тип"
            )
        return structured

    @staticmethod
    def _message_body(
        *,
        prompt: str,
        system: str,
        agent: str,
        provider_id: str,
        model_id: str,
    ) -> Dict[str, Any]:
        if bool(provider_id) != bool(model_id):
            raise OpenCodeProviderError(
                "Для явного выбора модели нужны оба значения: provider ID и model ID"
            )
        body: Dict[str, Any] = {
            "agent": agent,
            "parts": [{"type": "text", "text": prompt}],
        }
        if system:
            body["system"] = system
        if provider_id and model_id:
            body["model"] = {"providerID": provider_id, "modelID": model_id}
        return body

    def _send_message(
        self,
        *,
        session_id: str,
        body: Dict[str, Any],
        cancel_event: Optional[threading.Event],
        on_event: Optional[Callable[[Dict[str, Any]], None]],
    ) -> Dict[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
        sse_stop = threading.Event()
        sse_thread: Optional[threading.Thread] = None
        permission_thread: Optional[threading.Thread] = None
        if on_event is not None:
            sse_thread = threading.Thread(
                target=self._consume_session_events,
                args=(session_id, sse_stop, on_event),
                name=f"opencode-sse-{session_id[-8:]}",
                daemon=True,
            )
            sse_thread.start()
            permission_thread = threading.Thread(
                target=self._watch_pending_permissions,
                args=(session_id, sse_stop, on_event),
                name=f"opencode-permissions-{session_id[-8:]}",
                daemon=True,
            )
            permission_thread.start()
        try:
            try:
                response = _unwrap_data(
                    self._request(
                        "POST",
                        f"/session/{urllib.parse.quote(session_id, safe='')}/message",
                        body,
                    )
                )
            except Exception as exc:
                if cancel_event is not None and cancel_event.is_set():
                    raise OpenCodeCancelled("Операция отменена пользователем") from exc
                raise
        finally:
            sse_stop.set()
            if sse_thread is not None:
                sse_thread.join(timeout=1.0)
            if permission_thread is not None:
                permission_thread.join(timeout=1.0)
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
        if not isinstance(response, dict):
            raise OpenCodeError("Некорректный ответ OpenCode message endpoint")
        self._raise_message_error(response)
        return response

    @staticmethod
    def _raise_message_error(response: Mapping[str, Any]) -> None:
        info = response.get("info")
        if info is None:
            info = {}
        if not isinstance(info, dict):
            raise OpenCodeError("В ответе OpenCode поле info имеет неверный тип")
        error = info.get("error", response.get("error"))
        if not isinstance(error, dict):
            return
        name = str(error.get("name") or error.get("type") or "OpenCodeError")
        data = error.get("data") if isinstance(error.get("data"), dict) else error
        message = str(data.get("message", name)) if isinstance(data, dict) else name
        message = redact_text(message)[:2000]
        if name == "StructuredOutputError":
            raise OpenCodeStructuredOutputError(
                "OpenCode не смог сформировать структурированный результат: " + message
            )
        if name in {"ProviderAuthError", "AuthError"}:
            raise OpenCodeProviderError(message)
        if name in {"MessageAbortedError", "AbortedError"}:
            raise OpenCodeCancelled("OpenCode session была отменена")
        raise OpenCodeError(f"{name}: {message}")

    def iter_events(self, stop_event: threading.Event) -> Iterator[Dict[str, Any]]:
        """Читает instance SSE; незавершённый JSON наружу не выдаётся."""
        request = urllib.request.Request(
            self.base_url + "/event",
            method="GET",
            headers=self._headers(
                instance=True,
                extra={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
            ),
        )
        try:
            with self._opener.open(request, timeout=min(self.timeout, 5.0)) as response:
                data_lines: list[str] = []
                event_bytes = 0
                discard_event = False
                while not stop_event.is_set():
                    try:
                        raw = response.readline(MAX_SSE_EVENT_BYTES + 1)
                    except (socket.timeout, TimeoutError):
                        continue
                    if not raw:
                        break
                    if stop_event.is_set():
                        break
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if data_lines and not discard_event:
                            try:
                                event = json.loads("\n".join(data_lines))
                            except json.JSONDecodeError:
                                event = None
                            if isinstance(event, dict):
                                yield event
                        data_lines.clear()
                        event_bytes = 0
                        discard_event = False
                        continue
                    if line.startswith("data:") and not discard_event:
                        event_bytes += len(raw)
                        if event_bytes > MAX_SSE_EVENT_BYTES:
                            data_lines.clear()
                            discard_event = True
                        else:
                            data_lines.append(line[5:].lstrip())
        except (urllib.error.URLError, OSError):
            return

    def _consume_session_events(
        self,
        session_id: str,
        stop_event: threading.Event,
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        # SSE — канал прогресса, а не источник финального результата. Если он
        # оборвался, переподключаемся и параллельно проверяем persistent список
        # permissions: иначе HTTP message может ждать согласия, которое UI не увидел.
        disconnect_reported = False
        while not stop_event.is_set():
            received = False
            for event in self.iter_events(stop_event):
                received = True
                if isinstance(event.get("payload"), dict):
                    event = event["payload"]
                if self._event_session_id(event) != session_id:
                    continue
                self._safe_event_callback(callback, event, session_id)
            if stop_event.is_set():
                break
            if not disconnect_reported:
                self._safe_event_callback(
                    callback,
                    {
                        "type": "client.sse.disconnected",
                        "properties": {"sessionID": session_id},
                    },
                    session_id,
                )
                disconnect_reported = True
            if received:
                _log.info("SSE reconnect session=%s", session_id)
            stop_event.wait(0.35)

    def _watch_pending_permissions(
        self,
        session_id: str,
        stop_event: threading.Event,
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        seen: set[str] = set()
        while not stop_event.is_set():
            self._poll_pending_permissions(session_id, seen, callback)
            stop_event.wait(0.75)

    def _poll_pending_permissions(
        self,
        session_id: str,
        seen: set[str],
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        try:
            pending = self.list_pending_permissions(
                timeout=min(2.0, max(0.5, self.timeout)),
                quiet=True,
            )
        except Exception:
            return
        for request in pending:
            if str(request.get("sessionID") or "") != session_id:
                continue
            permission_id = str(request.get("id") or "")
            if not permission_id or permission_id in seen:
                continue
            seen.add(permission_id)
            self._safe_event_callback(
                callback,
                {"type": "permission.asked", "properties": request},
                session_id,
            )

    @staticmethod
    def _safe_event_callback(
        callback: Callable[[Dict[str, Any]], None],
        event: Dict[str, Any],
        session_id: str,
    ) -> None:
        try:
            callback(event)
        except Exception:
            _log.exception("OpenCode event callback failed session=%s", session_id)

    @staticmethod
    def _event_session_id(event: Mapping[str, Any]) -> Optional[str]:
        properties = event.get("properties")
        if not isinstance(properties, dict):
            return None
        if properties.get("sessionID"):
            return str(properties["sessionID"])
        for key in ("part", "info", "message"):
            nested = properties.get(key)
            if isinstance(nested, dict) and nested.get("sessionID"):
                return str(nested["sessionID"])
        return None

    def _headers(
        self,
        *,
        instance: bool,
        extra: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._password:
            token = base64.b64encode(
                f"{self.username}:{self._password}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        if instance and self.directory:
            # OpenCode 1.18.18 decodeURIComponent() делает обратное
            # преобразование. Заголовок остаётся ASCII и работает с Unicode path.
            normalized = self.directory.replace("\\", "/")
            headers["x-opencode-directory"] = urllib.parse.quote(
                normalized, safe="/:"
            )
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
        instance: bool = True,
        quiet: bool = False,
    ) -> Any:
        data = None
        headers = self._headers(instance=instance)
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        started = time.monotonic()
        if not quiet:
            _log.debug("request method=%s path=%s server=%s", method, path, self.base_url)
        try:
            with self._opener.open(
                request,
                timeout=self.timeout if timeout is None else timeout,
            ) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise OpenCodeError("Ответ OpenCode превышает допустимый размер")
                if not quiet:
                    _log.info(
                        "response method=%s path=%s status=%s duration_ms=%d bytes=%d",
                        method,
                        path,
                        getattr(response, "status", 200),
                        int((time.monotonic() - started) * 1000),
                        len(raw),
                    )
                if not raw.strip():
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise OpenCodeError("OpenCode вернул невалидный JSON") from exc
        except urllib.error.HTTPError as exc:
            raw = exc.read(16_384).decode("utf-8", errors="replace")
            # Не переносим response body в UI/исключение: provider способен
            # вернуть фрагмент prompt или внешних данных. Для диагностики
            # достаточно кода и безопасного машинного имени ошибки.
            message = "request failed"
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data_obj = parsed.get("data", parsed)
                    name = parsed.get("name")
                    if not name and isinstance(data_obj, dict):
                        name = data_obj.get("name") or data_obj.get("type")
                    if name:
                        message = str(name)[:200]
            except json.JSONDecodeError:
                pass
            if not quiet:
                _log.warning(
                    "http error method=%s path=%s status=%d duration_ms=%d",
                    method,
                    path,
                    exc.code,
                    int((time.monotonic() - started) * 1000),
                )
            raise OpenCodeHttpError(exc.code, message) from exc
        except (urllib.error.URLError, OSError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            if not quiet:
                _log.warning(
                    "connection error method=%s path=%s duration_ms=%d error_type=%s",
                    method,
                    path,
                    int((time.monotonic() - started) * 1000),
                    type(reason).__name__,
                )
            raise OpenCodeError(f"OpenCode недоступен: {reason}") from exc
