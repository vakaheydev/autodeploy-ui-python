"""
HttpClient — тонкая обёртка над urllib для HTTP запросов.
Не требует сторонних библиотек.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


class HttpError(Exception):
    """Ошибка HTTP запроса с кодом ответа и телом."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class HttpClient:
    """
    Простой HTTP клиент.
    Отвечает за выполнение GET/POST запросов с Bearer-авторизацией.

    Токен устанавливается через set_token() при смене окружения.
    """

    def __init__(self, token: str = "", timeout: int = 30) -> None:
        self._token = token
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Управление токеном
    # ------------------------------------------------------------------

    def set_token(self, token: str) -> None:
        """Обновляет Authorization токен (вызывается при смене окружения)."""
        self._token = token

    # ------------------------------------------------------------------
    # HTTP методы
    # ------------------------------------------------------------------

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET запрос. Возвращает десериализованный JSON."""
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = self._build_request(url, method="GET")
        return self._execute(req)

    def post(self, url: str, payload: Dict[str, Any]) -> Any:
        """POST запрос с JSON телом. Возвращает десериализованный JSON."""
        data = json.dumps(payload).encode("utf-8")
        req = self._build_request(url, method="POST", data=data)
        req.add_header("Content-Type", "application/json")
        return self._execute(req)

    def put(self, url: str, payload: Dict[str, Any]) -> Any:
        """PUT запрос с JSON телом."""
        data = json.dumps(payload).encode("utf-8")
        req = self._build_request(url, method="PUT", data=data)
        req.add_header("Content-Type", "application/json")
        return self._execute(req)

    def delete(self, url: str) -> Any:
        """DELETE запрос."""
        req = self._build_request(url, method="DELETE")
        return self._execute(req)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _build_request(
        self,
        url: str,
        method: str,
        data: Optional[bytes] = None,
    ) -> urllib.request.Request:
        req = urllib.request.Request(url, data=data, method=method)
        if self._token:
            req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/json")
        return req

    def _execute(self, req: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise HttpError(exc.code, body) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Ошибка соединения: {exc.reason}") from exc
