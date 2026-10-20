"""OpenCode 2.0.32 transport, projected onto AutoDeploy's stable AI contract.

The V1 client supplies localhost/auth/redaction and JSON-validation primitives.
V2 prompts are durable inbox items; only a subsequent idle marker completes a
turn. Polling the persisted projection also recovers progress missed by SSE.
"""
from __future__ import annotations

import base64
import re
import threading
import time
from typing import Any, Mapping
from urllib.parse import quote, urlencode

from .client import (
    OpenCodeCancelled, OpenCodeClient, OpenCodeError, OpenCodeHealth,
    OpenCodeModel, OpenCodeModelCatalog, OpenCodeModelSelection,
    _positive_integer, _unwrap_data,
)


def _permission(request: Mapping[str, Any]) -> dict[str, Any]:
    return {**request, "permission": request.get("action", ""),
            "patterns": request.get("resources", [])}


def _message(raw: Mapping[str, Any], session_id: str) -> dict[str, Any]:
    """Never project reasoning, provider state or raw error response bodies."""
    kind = raw.get("type")
    model = raw.get("model") or {}
    info = {key: raw[key] for key in ("id", "time", "tokens", "cost", "finish", "agent") if key in raw}
    info.update(role=kind, sessionID=session_id,
                providerID=model.get("providerID", ""), modelID=model.get("id", ""))
    if isinstance(raw.get("error"), dict):
        info["error"] = {"type": raw["error"].get("type", "OpenCodeError")}
    parts = []
    content = raw.get("content", []) if kind == "assistant" else (
        [{"type": "text", "text": raw.get("text", "")}] if kind == "user" else []
    )
    for index, item in enumerate(content):
        if not isinstance(item, dict) or item.get("type") not in {"text", "tool"}:
            continue
        part = {"id": f"{raw.get('id', '')}:{index}", "messageID": raw.get("id"),
                "sessionID": session_id, "type": item["type"]}
        if item["type"] == "text":
            part["text"] = item.get("text", "")
        else:
            state = item.get("state") or {}
            timing = item.get("time") or {}
            part.update(callID=item.get("id"), tool=item.get("name"), state={
                "status": "pending" if state.get("status") == "streaming" else state.get("status"),
                "input": state.get("input", {}),
                "output": "\n".join(str(x.get("text", "")) for x in state.get("content", [])
                                    if isinstance(x, dict) and x.get("type") == "text"),
                "time": {"start": timing.get("ran", timing.get("created")), "end": timing.get("completed")},
            })
            if state.get("error"):
                part["state"]["error"] = str(state["error"].get("type", "ToolError"))
        parts.append(part)
    return {"info": info, "parts": parts}


class OpenCodeV2Client(OpenCodeClient):
    """Native V2 API; no fallback that could silently drop session permissions."""

    supports_message_queue = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # V2 fixes this identity server-side; a saved V1 username is not valid.
        self.username = "opencode"
        self._mcp_lock = threading.Lock()
        self._direct_mcp: dict[str, dict[str, Any]] = {}
        self._queue_lock = threading.RLock()
        self._active_queues: set[str] = set()

    def list_message_queue(self, session_id):
        rows = _unwrap_data(self._wire("GET", f"/api/session/{quote(session_id, safe='')}/inbox", quiet=True))
        if not isinstance(rows, list):
            raise OpenCodeError("Некорректный ответ очереди OpenCode")
        return [row for row in rows if row.get("type") == "user" and row.get("delivery") == "queue"]

    def enqueue_message(self, session_id, text, *, metadata=None, require_active=False):
        # Admission and settling share a lock: an accepted prompt must always
        # have an observer, even when it races the last idle marker.
        with self._queue_lock:
            if require_active and session_id not in self._active_queues:
                raise OpenCodeError("Текущий ответ уже завершён или ещё не начат; отправьте сообщение снова")
            result = _unwrap_data(self._wire("POST", f"/api/session/{quote(session_id, safe='')}/prompt", {
                "text": text, "delivery": "queue", "resume": True,
                "metadata": metadata or {},
            }))
            if not isinstance(result, dict) or not result.get("id"):
                raise OpenCodeError("OpenCode не вернул ID сообщения очереди")
            return result

    def cancel_queued_message(self, session_id, message_id):
        self._wire("DELETE", f"/api/session/{quote(session_id, safe='')}/inbox/{quote(message_id, safe='')}")

    def resume_message_queue(self, session_id, *, cancel_event=None, on_event=None):
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
        rows = self.list_message_queue(session_id)
        if not rows:
            raise OpenCodeError("Очередь OpenCode пуста")
        first = rows[0]
        path = f"/api/session/{quote(session_id, safe='')}"
        # Re-admission by ID is idempotent and wakes the existing native inbox.
        self._wire("POST", path + "/prompt", {
            "id": first["id"], "text": first["payload"]["text"], "resume": True,
            "delivery": "queue",
        })
        with self._queue_lock:
            self._active_queues.add(session_id)
        return self._wait_for_message(session_id, first["id"], cancel_event, on_event,
                                      native_queue=True, initial_user=first)

    def _wire(self, method: str, path: str, payload=None, **kwargs) -> Any:
        return super()._request(method, path, payload, **kwargs)

    def session_web_url(self, session_id: str) -> str:
        # Reuse validation; the V2 UI removed directory-scoped routes.
        super().session_web_url(session_id)
        server = base64.urlsafe_b64encode(self.base_url.encode()).decode().rstrip("=")
        return f"{self.base_url}/server/{server}/session/{session_id.strip()}"

    def create_session(self, title="", *, mcp_names=(), **kwargs):
        if mcp_names:
            with self._mcp_lock:
                self._prepare_direct_mcp(mcp_names)
        return super().create_session(title, mcp_names=mcp_names, **kwargs)

    def _prepare_direct_mcp(self, names):
        # Native V2 hides MCP tools inside Code Mode by default. Expose only
        # selected servers directly in this isolated location; keep execute
        # denied and retain exact per-tool session rules.
        entries = self._wire("GET", "/api/config")
        if not isinstance(entries, list):
            raise OpenCodeError("Некорректный ответ OpenCode /api/config")
        servers = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            servers.update(((entry.get("info") or {}).get("mcp") or {}).get("servers") or {})
        for name in names:
            config = servers.get(name)
            if not isinstance(config, dict):
                raise OpenCodeError(f"MCP {name!r} отсутствует в конфигурации OpenCode")
            if config.get("codemode") is not False and self._direct_mcp.get(name) != config:
                self._wire("PUT", f"/api/experimental/mcp/{quote(name, safe='')}",
                           {"config": {**config, "codemode": False}})
                deadline = time.monotonic() + min(10.0, self.timeout)
                while True:
                    status = self.list_mcp_servers(timeout=max(0.1, deadline - time.monotonic())).get(name, {})
                    if status.get("status") == "connected":
                        # V2 debounces ToolsChanged by 100 ms after connecting.
                        # There is no public registry-settled endpoint in 2.0.32.
                        time.sleep(0.2)
                        break
                    if status.get("status") != "pending" or time.monotonic() >= deadline:
                        raise OpenCodeError(f"MCP {name!r} не подключён после настройки V2")
                    time.sleep(0.1)
                self._direct_mcp[name] = dict(config)

    def health(self, timeout=None) -> OpenCodeHealth:
        value = self._wire("GET", "/api/info", timeout=timeout, instance=False)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            raise OpenCodeError("Некорректный ответ OpenCode /api/info; требуется 2.0.32")
        if not value["version"].removeprefix("v").startswith("2."):
            raise OpenCodeError("Требуется OpenCode 2.0.32")
        return OpenCodeHealth(True, value["version"])

    def _pages(self, path: str, *, timeout=None, query=None) -> list[dict[str, Any]]:
        params = dict(query or {})
        params.setdefault("limit", 200)
        result = []
        seen = set()
        while True:
            page = self._wire("GET", path + "?" + urlencode(params), timeout=timeout, quiet=True)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise OpenCodeError("Некорректный paginated ответ OpenCode")
            result.extend(x for x in page["data"] if isinstance(x, dict))
            cursor = (page.get("cursor") or {}).get("next")
            if not cursor:
                return result
            if not isinstance(cursor, str) or cursor in seen:
                raise OpenCodeError("OpenCode повторил cursor страницы")
            seen.add(cursor)
            params.pop("order", None)
            params["cursor"] = cursor

    def _request(self, method, path, payload=None, **kwargs):
        """Translate only the stable methods reused from the base client."""
        if path == "/session" and method == "POST":
            body = dict(payload or {})
            # Session rules are evaluated after agent rules: last match wins.
            body["permissions"] = [
                {"action": re.sub(r"[^A-Za-z0-9_*?-]", "_", rule["permission"]),
                 "resource": rule["pattern"], "effect": rule["action"]}
                for rule in body.pop("permission")
            ]
            if self.directory:
                body["location"] = {"directory": self.directory}
            return self._wire(method, "/api/session", body, **kwargs)
        if path == "/session" and method == "GET":
            return self._pages("/api/session", timeout=kwargs.get("timeout"),
                               query={"directory": self.directory} if self.directory else {})
        if path.endswith("/message") and method == "GET":
            session_id = path.split("/")[2]
            return [_message(x, session_id) for x in self._pages(
                "/api" + path, timeout=kwargs.get("timeout"), query={"order": "asc"}
            ) if x.get("type") in {"user", "assistant"}]
        if path.endswith("/abort"):
            return self._wire("POST", "/api" + path[:-6] + "/interrupt", {"resume": False}, **kwargs)
        if path == "/permission":
            value = _unwrap_data(self._wire("GET", "/api/permission/request", **kwargs))
            if not isinstance(value, list):
                raise OpenCodeError("Некорректный ответ списка разрешений OpenCode")
            return [_permission(x) for x in value if isinstance(x, dict)]
        if path == "/mcp":
            value = _unwrap_data(self._wire("GET", "/api/mcp", **kwargs))
            if not isinstance(value, list):
                raise OpenCodeError("Некорректный ответ OpenCode /api/mcp")
            return {x["name"]: x["status"] for x in value
                    if isinstance(x, dict) and isinstance(x.get("status"), dict) and x.get("name")}
        if path == "/agent" or re.fullmatch(r"/session/[^/]+", path):
            return self._wire(method, "/api" + path, payload, **kwargs)
        raise OpenCodeError("Неподдерживаемая операция OpenCode V2")

    def provider_status(self, timeout=None):
        providers = _unwrap_data(self._wire("GET", "/api/provider", timeout=timeout))
        if not isinstance(providers, list):
            raise OpenCodeError("Некорректный ответ OpenCode /api/provider")
        # Availability is determined by enabled models, not stored credentials.
        models = self.list_configured_models(timeout=timeout)
        connected = sorted({m.provider_id for m in models})
        return {"all": [{"id": x.get("id"), "name": x.get("name")} for x in providers
                        if isinstance(x, dict)], "connected": connected}

    def list_configured_models(self, timeout=None):
        providers = _unwrap_data(self._wire("GET", "/api/provider", timeout=timeout))
        models = _unwrap_data(self._wire("GET", "/api/model", timeout=timeout))
        if not isinstance(providers, list) or not isinstance(models, list):
            raise OpenCodeError("Некорректный каталог моделей OpenCode V2")
        names = {x.get("id"): x.get("name") for x in providers if isinstance(x, dict)}
        return [OpenCodeModel(
            provider_id=x["providerID"], model_id=x["id"],
            provider_name=str(names.get(x["providerID"]) or x["providerID"]),
            model_name=str(x.get("name") or x["id"]),
            variants=tuple(v["id"] for v in x.get("variants", []) if isinstance(v, dict) and v.get("id")),
            context_limit=_positive_integer((x.get("limit") or {}).get("context")),
        ) for x in models if isinstance(x, dict) and x.get("enabled") is True
            and x.get("providerID") and x.get("id")]

    def configured_model_catalog(self, *, agent_name="", timeout=None):
        models = tuple(self.list_configured_models(timeout=timeout))
        ref = None
        if agent_name:
            ref = next((x.get("model") for x in self.list_agents(timeout=timeout)
                        if agent_name in (x.get("id"), x.get("name"))), None)
        if not ref:
            ref = _unwrap_data(self._wire("GET", "/api/model/default", timeout=timeout))
        selection = None
        if isinstance(ref, dict):
            match = next((m for m in models if (m.provider_id, m.model_id) ==
                          (ref.get("providerID"), ref.get("id"))), None)
            if match:
                variant = ref.get("variant", "")
                selection = OpenCodeModelSelection(match.provider_id, match.model_id,
                                                   variant if variant in match.variants else "")
        return OpenCodeModelCatalog(models, selection)

    def respond_permission(self, session_id, permission_id, response):
        if response not in {"once", "always", "reject"}:
            raise ValueError("Некорректный ответ на permission request")
        self._wire("POST", f"/api/session/{quote(session_id, safe='')}/permission/"
                   f"{quote(permission_id, safe='')}/reply", {"decision": response})

    def _configure_turn(self, session_id, body):
        path = f"/api/session/{quote(session_id, safe='')}"
        if body.get("agent"):
            self._wire("POST", path + "/agent", {"agent": body["agent"]})
        if body.get("model"):
            model = {"providerID": body["model"]["providerID"], "id": body["model"]["modelID"]}
            if body.get("variant"):
                model["variant"] = body["variant"]
            self._wire("POST", path + "/model", {"model": model})
        instructions = (f"/api/experimental/session/{quote(session_id, safe='')}"
                        "/instructions/entries/autodeploy")
        if body.get("system"):
            self._wire("PUT", instructions, {"value": body["system"]})
        else:
            self._wire("DELETE", instructions)
        return path

    def add_session_context(self, *, session_id, prompt, system="", agent,
                            provider_id="", model_id="", variant=""):
        body = self._message_body(prompt=prompt, system=system, agent=agent,
                                  provider_id=provider_id, model_id=model_id, variant=variant)
        path = self._configure_turn(session_id, body)
        self._wire("POST", path + "/prompt", {"text": prompt, "resume": False})

    def _send_message(self, *, session_id, body, cancel_event, on_event):
        cancel = cancel_event if cancel_event is not None else threading.Event()
        if cancel.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
        path = self._configure_turn(session_id, body)
        if cancel.is_set():
            raise OpenCodeCancelled("Операция отменена пользователем")
        admitted = _unwrap_data(self._wire("POST", path + "/prompt", {
            "text": "\n".join(x["text"] for x in body["parts"] if x.get("type") == "text"),
            "resume": True,
            "delivery": "queue",
        }))
        if not isinstance(admitted, dict) or not admitted.get("id"):
            raise OpenCodeError("OpenCode не вернул ID принятого prompt")
        prompt_id = admitted["id"]
        native_queue = body.get("agent") == "autodeploy-copilot" and on_event is not None
        if native_queue:
            with self._queue_lock:
                self._active_queues.add(session_id)
        return self._wait_for_message(session_id, prompt_id, cancel, on_event, native_queue=native_queue)

    def _wait_for_message(self, session_id, prompt_id, cancel_event, on_event,
                          *, native_queue=False, initial_user=None):
        cancel = cancel_event if cancel_event is not None else threading.Event()
        path = f"/api/session/{quote(session_id, safe='')}"
        deadline = time.monotonic() + self.timeout
        seen_parts = {}
        seen_permissions = set()
        seen_users = set()
        completed_turns = set()
        last_queue = None

        def emit(kind, properties):
            if on_event:
                self._safe_event_callback(on_event, {"type": kind, "properties": properties}, session_id)

        try:
            while True:
                if cancel.is_set():
                    raise OpenCodeCancelled("Операция отменена пользователем")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OpenCodeError("Истёк timeout ответа OpenCode")
                # Read newest-first until the admitted prompt is reached. This
                # excludes old idle markers even if generation has not started.
                rows = self._turn_messages(path, prompt_id, min(2.0, remaining))
                replies = []
                current_user = prompt_id
                if initial_user and rows and prompt_id not in seen_users:
                    seen_users.add(prompt_id)
                    emit("client.queue.user", initial_user)
                for index, raw in enumerate(rows):
                    if native_queue and raw.get("type") == "user":
                        if current_user not in completed_turns and replies:
                            completed_turns.add(current_user)
                            emit("client.queue.reply", {"messages": replies})
                        current_user = raw.get("id", "")
                        replies = []
                        if current_user not in seen_users:
                            seen_users.add(current_user)
                            deadline = time.monotonic() + self.timeout
                            emit("client.queue.user", raw)
                    if raw.get("type") == "assistant":
                        projected = _message(raw, session_id)
                        replies.append(projected)
                        if on_event:
                            for part in projected["parts"]:
                                if seen_parts.get(part["id"]) == part:
                                    continue
                                seen_parts[part["id"]] = part
                                self._safe_event_callback(on_event, {
                                    "type": "message.part.updated", "properties": {"part": part},
                                }, session_id)
                    if raw.get("type") == "idle":
                        if (native_queue and raw.get("outcome") == "succeeded"
                                and any(item.get("type") == "user" for item in rows[index + 1:])):
                            continue
                        if raw.get("outcome") == "interrupted":
                            raise OpenCodeCancelled("OpenCode session была отменена")
                        if raw.get("outcome") == "failed":
                            self._raise_message_error(_message(raw, session_id))
                            raise OpenCodeError("OpenCode завершил выполнение с ошибкой")
                        if not replies:
                            raise OpenCodeError("OpenCode завершил turn без ответа ассистента")
                        final = replies[-1]
                        self._raise_message_error(final)
                        if native_queue:
                            with self._queue_lock:
                                pending = self.list_message_queue(session_id)
                                if pending:
                                    continue
                                if self._turn_messages(path, prompt_id, min(2.0, remaining)) != rows:
                                    continue  # An admission already left the inbox after our first read.
                                self._active_queues.discard(session_id)
                            final = {**final, "_turn_messages": replies}
                        return final
                if native_queue:
                    pending = self.list_message_queue(session_id)
                    if pending != last_queue:
                        last_queue = pending
                        emit("client.queue.updated", {"items": pending})
                if on_event:
                    self._poll_pending_permissions(session_id, seen_permissions, on_event)
                cancel.wait(min(0.25, max(0, deadline - time.monotonic())))
        except (OpenCodeCancelled, OpenCodeError) as exc:
            with self._queue_lock:
                self._active_queues.discard(session_id)
            # Interrupt does not remove a still-pending V2 inbox item.
            # Cancel admission first so it cannot unexpectedly run on a later wake.
            try:
                if initial_user is None:
                    self.cancel_queued_message(session_id, prompt_id)
            except OpenCodeError:
                pass
            # A timed-out async prompt must not keep executing unseen MCP calls.
            try:
                self.abort_session(session_id)
            except OpenCodeError:
                pass
            if cancel.is_set():
                raise OpenCodeCancelled("Операция отменена пользователем") from exc
            raise
        finally:
            if native_queue:
                with self._queue_lock:
                    self._active_queues.discard(session_id)

    def _turn_messages(self, path, prompt_id, timeout):
        params = {"order": "desc", "limit": 200}
        result = []
        cursors = set()
        while True:
            page = self._wire("GET", path + "/message?" + urlencode(params), timeout=timeout, quiet=True)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise OpenCodeError("Некорректный ответ истории OpenCode")
            for raw in page["data"]:
                if raw.get("id") == prompt_id:
                    return list(reversed(result))
                result.append(raw)
            cursor = (page.get("cursor") or {}).get("next")
            if not cursor:
                return []  # Prompt is still in the durable inbox.
            if cursor in cursors:
                raise OpenCodeError("OpenCode повторил cursor истории")
            cursors.add(cursor)
            params = {"cursor": cursor, "limit": 200}
