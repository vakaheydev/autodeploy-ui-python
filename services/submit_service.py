"""
SubmitService — отправка заполненной формы на удалённый сервис.
"""
import json
from typing import Any, Dict, Tuple

from core.env_manager import EnvManager
from core.http_client import HttpClient, HttpError
from config.environments import gravitee_token_key
from forms.base_form import BaseForm


class SubmitResult:
    """Результат отправки формы."""

    def __init__(self, success: bool, message: str, raw_response: Any = None) -> None:
        self.success = success
        self.message = message
        self.raw_response = raw_response

    def __bool__(self) -> bool:
        return self.success


class SubmitService:
    """
    Отвечает за:
      1. Валидацию данных формы
      2. Сборку payload через form.build_payload()
      3. Обновление токена под текущее окружение
      4. Отправку HTTP запроса
      5. Возврат структурированного результата
    """

    def __init__(self, http_client: HttpClient, env_manager: EnvManager) -> None:
        self._client = http_client
        self._env_manager = env_manager

    def submit(
        self,
        form: BaseForm,
        form_data: Dict[str, Any],
        environment: str,
    ) -> SubmitResult:
        """
        Выполняет полный цикл отправки формы.
        Возвращает SubmitResult с признаком успеха и сообщением.
        """
        # 1. Валидация
        errors = form.validate(form_data)
        if errors:
            return SubmitResult(False, "\n".join(errors))

        # 2. Endpoint
        endpoint = form.get_submit_endpoint(environment)
        if not endpoint:
            return SubmitResult(
                False,
                f"URL не задан для окружения '{environment}'. "
                "Откройте форму и добавьте URL в get_submit_endpoint().",
            )

        # 3. Обновить токен под текущее окружение
        token = self._env_manager.get(gravitee_token_key(environment))
        self._client.set_token(token)

        # 4. Собрать payload
        payload = form.build_payload(form_data)

        # 5. Отправить
        method = form.get_http_method().upper()
        try:
            if method == "POST":
                response = self._client.post(endpoint, payload)
            elif method == "PUT":
                response = self._client.put(endpoint, payload)
            else:
                return SubmitResult(False, f"HTTP метод '{method}' не поддерживается")
        except HttpError as exc:
            return SubmitResult(
                False,
                f"Сервер вернул ошибку {exc.status}:\n{exc.body}",
                raw_response=exc.body,
            )
        except ConnectionError as exc:
            return SubmitResult(False, str(exc))
        except Exception as exc:
            return SubmitResult(False, f"Неожиданная ошибка: {exc}")

        # 6. Успех
        pretty = json.dumps(response, ensure_ascii=False, indent=2)
        return SubmitResult(
            True,
            f"Успешно отправлено в '{environment}'",
            raw_response=response,
        )
