"""
HttpClient — тонкая обёртка над urllib для HTTP запросов.
Не требует сторонних библиотек.
"""
import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)


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
        self._auth_header: Optional[str] = None  # переопределяет _token если задан

    # ------------------------------------------------------------------
    # Управление авторизацией
    # ------------------------------------------------------------------

    def set_token(self, token: str) -> None:
        """Bearer-авторизация. Вызывается при смене окружения."""
        self._token = token
        self._auth_header = None

    def set_basic_auth(self, login: str, password: str) -> None:
        """Basic-авторизация (login:password → base64). Вызывается при смене окружения."""
        encoded = base64.b64encode(f"{login}:{password}".encode()).decode("ascii")
        self._auth_header = f"Basic {encoded}"
        self._token = ""

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
        if self._auth_header:
            req.add_header("Authorization", self._auth_header)
        elif self._token:
            try:
                self._token.encode("ascii")
            except UnicodeEncodeError:
                raise ValueError(
                    "Токен авторизации содержит недопустимые символы. "
                    "Проверьте значение токена в настройках окружения."
                )
            req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/json")
        return req

    def _execute(self, req: urllib.request.Request) -> Any:
        method = req.get_method()
        url = req.full_url
        _start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
                elapsed = time.monotonic() - _start
                _log.info("%s %s → %d  (%.2fs)", method, url, resp.status, elapsed)
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            elapsed = time.monotonic() - _start
            _log.warning("%s %s → %d  (%.2fs)", method, url, exc.code, elapsed)
            body = exc.read().decode("utf-8", errors="replace")
            raise HttpError(exc.code, body) from exc
        except urllib.error.URLError as exc:
            elapsed = time.monotonic() - _start
            _log.error("%s %s → ERROR  (%.2fs): %s", method, url, elapsed, exc.reason)
            raise ConnectionError(f"Ошибка соединения: {exc.reason}") from exc
