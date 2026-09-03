"""ITSMService — получение необработанных данных заявки для ContextBuilder."""
from __future__ import annotations

import urllib.parse
from typing import Any

from config.environments import (
    ITSM_LOGIN_KEY,
    ITSM_PASSWORD_KEY,
    ITSM_TICKET_URL_TEMPLATE_KEY,
)
from core.env_manager import EnvManager
from core.http_client import HttpClient


class ITSMService:

    def __init__(self, env_manager: EnvManager, http_client: HttpClient) -> None:
        self._env_manager = env_manager
        self._http_client = http_client

    def get_ticket(self, ticket_id: str, environment: str = "") -> Any:
        """Возвращает JSON заявки. Маппинг полей намеренно выполняет AI-слой."""
        if not ticket_id or not ticket_id.strip():
            raise ValueError("Не указан ID ITSM-заявки")
        clean_ticket_id = ticket_id.strip()
        if len(clean_ticket_id) > 200:
            raise ValueError("ID ITSM-заявки превышает 200 символов")
        settings = self._env_manager.load()
        template = self._setting_for_environment(
            settings, ITSM_TICKET_URL_TEMPLATE_KEY, environment
        )
        if not template:
            raise RuntimeError(
                "Не настроен ITSM_TICKET_URL_TEMPLATE. "
                "Укажите URL-шаблон с {ticket_id} в настройках."
            )
        if "{ticket_id}" not in template:
            raise RuntimeError("ITSM_TICKET_URL_TEMPLATE должен содержать {ticket_id}")

        safe_ticket_id = urllib.parse.quote(clean_ticket_id, safe="-_.")
        try:
            url = template.format(
                ticket_id=safe_ticket_id,
                environment=urllib.parse.quote(environment, safe="-_"),
            )
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"Некорректный ITSM URL-шаблон: {exc}") from exc
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise RuntimeError("ITSM URL должен быть корректным HTTP(S)-адресом без credentials")

        login = settings.get(ITSM_LOGIN_KEY, "")
        password = settings.get(ITSM_PASSWORD_KEY, "")
        if not login or not password:
            raise RuntimeError("Не настроены ITSM_LOGIN и ITSM_PASSWORD")

        # Отдельный клиент исключает гонку auth state с параллельными ADO/Gravitee запросами.
        client = HttpClient(
            timeout=30,
            allow_redirects=False,
            max_response_bytes=10 * 1024 * 1024,
        )
        client.set_basic_auth(login, password)
        return client.get(url)

    @staticmethod
    def _setting_for_environment(settings: dict[str, str], key: str, environment: str) -> str:
        env_key = f"{key}_{environment.upper()}" if environment else ""
        return settings.get(env_key, "") or settings.get(key, "")
