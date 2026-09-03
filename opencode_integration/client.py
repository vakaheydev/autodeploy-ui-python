"""Минимальный Python-клиент OpenCode Server 1.18.x."""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Optional

from opencode_integration.context_builder import redact_text

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_SSE_EVENT_BYTES = 512 * 1024


class OpenCodeError(RuntimeError):
    """Базовая безопасная ошибка интеграции."""


class OpenCodeHttpError(OpenCodeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"OpenCode HTTP {status}: {redact_text(message)[:2000]}")


class OpenCodeStructuredOutputError(OpenCodeError):
    """Модель не смогла сформировать structured_output."""


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


def _unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and set(value).intersection({"data", "error"}) and "data" in value:
        return value["data"]
    return value


class OpenCodeClient:
    """HTTP/SSE-клиент без внешних зависимостей и без доступа не к localhost."""

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
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
            raise ValueError("OpenCode Server разрешён только по http://127.0.0.1")
        if parsed.port is None:
            raise ValueError("В адресе OpenCode Server должен быть указан порт")
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        # Не позволяем HTTP_PROXY перенаправить локальный чувствительный prompt.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def health(self, timeout: Optional[float] = None) -> OpenCodeHealth:
        payload = self._request("GET", "/global/health", timeout=timeout)
        payload = _unwrap_data(payload)
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

    def has_agent(self, agent_name: str, timeout: Optional[float] = None) -> bool:
        for agent in self.list_agents(timeout=timeout):
            if agent.get("name") == agent_name or agent.get("id") == agent_name:
                return True
        return False

    def require_agent(self, agent_name: str, timeout: Optional[float] = None) -> None:
        for agent in self.list_agents(timeout=timeout):
            if agent.get("name") != agent_name and agent.get("id") != agent_name:
                continue
            mode = agent.get("mode")
            if mode not in (None, "primary"):
                raise OpenCodeAgentMissingError(
                    f"Агент {agent_name!r} загружен не как primary"
                )
            return
        raise OpenCodeAgentMissingError(
            f"OpenCode не загрузил обязательного агента {agent_name!r}"
        )

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

    def create_session(self, title: str) -> str:
        payload = _unwrap_data(self._request("POST", "/session", {"title": title[:200]}))
        if not isinstance(payload, dict) or not payload.get("id"):
            raise OpenCodeError("OpenCode не вернул ID созданной session")
        return str(payload["id"])

    def delete_session(self, session_id: str) -> None:
        self._request(
            "DELETE",
            f"/session/{urllib.parse.quote(session_id, safe='')}",
            timeout=min(5.0, max(0.5, self.timeout)),
        )

    def abort_session(self, session_id: str) -> None:
        self._request(
            "POST",
            f"/session/{urllib.parse.quote(session_id, safe='')}/abort",
            timeout=min(5.0, max(0.5, self.timeout)),
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
    ) -> Dict[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
        if bool(provider_id) != bool(model_id):
            raise OpenCodeProviderError(
                "Для явного выбора модели нужны оба значения: provider ID и model ID"
            )

        body: Dict[str, Any] = {
            "agent": agent,
            "system": system,
            "parts": [{"type": "text", "text": prompt}],
            "format": {
                "type": "json_schema",
                "schema": schema,
                "retryCount": max(0, int(retry_count)),
            },
        }
        if provider_id and model_id:
            body["model"] = {"providerID": provider_id, "modelID": model_id}

        sse_stop = threading.Event()
        sse_thread: Optional[threading.Thread] = None
        if on_event is not None:
            sse_thread = threading.Thread(
                target=self._consume_session_events,
                args=(session_id, sse_stop, on_event),
                name="opencode-sse",
                daemon=True,
            )
            sse_thread.start()

        try:
            try:
                response = _unwrap_data(self._request(
                    "POST",
                    f"/session/{urllib.parse.quote(session_id, safe='')}/message",
                    body,
                ))
            except Exception as exc:
                if cancel_event is not None and cancel_event.is_set():
                    raise OpenCodeCancelled("Операция отменена пользователем") from exc
                raise
        finally:
            sse_stop.set()
            if sse_thread is not None:
                sse_thread.join(timeout=1.0)

        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
        if not isinstance(response, dict):
            raise OpenCodeError("Некорректный ответ OpenCode message endpoint")
        info = response.get("info")
        if info is None:
            info = {}
        if not isinstance(info, dict):
            raise OpenCodeError("В ответе OpenCode поле info имеет неверный тип")

        error = info.get("error", response.get("error"))
        if isinstance(error, dict):
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

        # OpenCode 1.18.18 называет поле `structured`; в некоторых сборках SDK
        # и более ранней документации встречается `structured_output`.
        structured = None
        for container in (info, response):
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

    def iter_events(self, stop_event: threading.Event) -> Iterator[Dict[str, Any]]:
        """Читает `/event` как SSE; незавершённый JSON наружу не выдаётся."""
        req = urllib.request.Request(
            self.base_url + "/event",
            method="GET",
            headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
        )
        try:
            with self._opener.open(req, timeout=min(self.timeout, 5.0)) as response:
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
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if data_lines and not discard_event:
                            joined = "\n".join(data_lines)
                            data_lines.clear()
                            try:
                                event = json.loads(joined)
                            except json.JSONDecodeError:
                                continue
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
        for event in self.iter_events(stop_event):
            if isinstance(event.get("payload"), dict):
                event = event["payload"]
            properties = event.get("properties", {})
            event_session = properties.get("sessionID") if isinstance(properties, dict) else None
            if event_session in (None, session_id):
                try:
                    callback(event)
                except Exception:
                    # UI progress callback не должен ломать extraction.
                    continue
        if not stop_event.is_set():
            try:
                callback({"type": "client.sse.disconnected", "properties": {}})
            except Exception:
                pass

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise OpenCodeError("Ответ OpenCode превышает допустимый размер")
                if not raw.strip():
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise OpenCodeError("OpenCode вернул невалидный JSON") from exc
        except urllib.error.HTTPError as exc:
            raw = exc.read(16_384).decode("utf-8", errors="replace")
            message = raw
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data_obj = parsed.get("data", parsed)
                    if isinstance(data_obj, dict):
                        message = str(data_obj.get("message", parsed.get("name", raw)))
            except json.JSONDecodeError:
                pass
            raise OpenCodeHttpError(exc.code, message) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            raise OpenCodeError(f"OpenCode недоступен: {reason}") from exc
