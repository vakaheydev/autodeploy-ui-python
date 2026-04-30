"""
BaseForm — абстрактный базовый класс для всех форм приложения.

Как добавить новую форму:
  1. Создать класс, унаследованный от BaseForm
  2. Реализовать все абстрактные свойства/методы
  3. Зарегистрировать экземпляр в forms/loader.py
"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field as _dc_field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from services.gravitee_service import GraviteeService
    from services.itsm_service import ITSMService
    from services.tfs_service import TfsService

from forms.fields import FieldDefinition
from forms.result_config import ResultScreenConfig, ResultStatus


@dataclass
class CustomButton:
    """
    Декларация кастомной кнопки в футере формы.

    label   — текст на кнопке.
    handler — вызывается на главном потоке: handler(environment: str) -> None
              Внутри handler доступны self.screen (FormScreen, использовать как parent
              для диалогов) и self.screen.apply_form_data() для предзаполнения полей.
    style   — "Primary" или "Secondary" (по умолчанию Secondary).
    """
    label: str
    handler: Callable[[str], None]
    style: str = "Secondary"


class BaseForm(ABC):
    """
    Декларативное описание формы.
    Знает о структуре данных, но НЕ знает об UI и HTTP деталях реализации.
    """

    # Инжектируются FormScreen'ом перед открытием формы
    tfs_service:      Optional["TfsService"]      = None
    itsm_service:     Optional["ITSMService"]     = None
    gravitee_service: Optional["GraviteeService"] = None
    screen:           Optional[Any]               = None  # ссылка на FormScreen (tk.Widget)

    # ------------------------------------------------------------------
    # Обязательные свойства — идентификация формы
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def form_id(self) -> str:
        """Уникальный идентификатор формы. Пример: 'api.create'."""
        ...

    @property
    @abstractmethod
    def title(self) -> str:
        """Отображаемое название формы."""
        ...

    @property
    @abstractmethod
    def category(self) -> str:
        """
        Категория формы ('api', 'apps', 'other').
        Должна совпадать с ключами в config/categories.py.
        """
        ...

    # ------------------------------------------------------------------
    # Структура формы
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def fields(self) -> List[FieldDefinition]:
        """Упорядоченный список полей формы."""
        ...

    # ------------------------------------------------------------------
    # Бизнес-логика
    # ------------------------------------------------------------------

    @abstractmethod
    def build_payload(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Преобразует данные формы (ключи = field.key) в JSON payload
        для отправки на сервер.

        form_data: {field.key: значение, ...}
        Возвращает словарь, который будет сериализован в JSON.
        """
        ...

    @abstractmethod
    def get_submit_endpoint(self, environment: str) -> str:
        """
        Возвращает URL для отправки формы в заданном окружении.
        Если окружение не поддерживается — вернуть пустую строку.
        """
        ...

    def get_http_method(self) -> str:
        """HTTP метод отправки. По умолчанию POST. Переопределить при необходимости."""
        return "POST"

    def get_submit_headers(self, environment: str) -> Dict[str, str]:
        """
        Дополнительные HTTP заголовки для запроса (если нужны).
        По умолчанию пустой словарь — авторизация добавляется автоматически.
        """
        return {}

    def confirm_submit(self) -> bool:
        """
        Показывать ли диалог подтверждения перед отправкой формы.
        По умолчанию False — форма отправляется без лишнего шага.

        Включить для необратимых или критичных операций:
            return True
        """
        return False

    def build_confirm_text(
        self,
        environment: str,
        endpoint: str,
        method: str,
        payload: Dict[str, Any],
    ) -> str:
        """
        Генерирует текст для диалога подтверждения сабмита.
        Переопределить для кастомного сообщения (например, человекочитаемое резюме).

        По умолчанию показывает метод, URL, окружение и JSON payload.
        """
        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            f"Метод:      {method}\n"
            f"URL:        {endpoint}\n"
            f"Окружение:  {environment}\n\n"
            f"Payload:\n{payload_str}"
        )

    def get_auth_type(self) -> str:
        """
        Тип авторизации при отправке формы. Возможные значения:
          "gravitee" — Bearer GRAVITEE_TOKEN_<ENV_KEY> (по умолчанию)
          "tfs"      — Bearer TFS_TOKEN
          "itsm"     — Basic ITSM_LOGIN:ITSM_PASSWORD
          "none"     — без авторизации

        Переопределить, если форма обращается не к Gravitee.
        """
        return "gravitee"

    # ------------------------------------------------------------------
    # Экран результата
    # ------------------------------------------------------------------

    def get_result_config(self) -> ResultScreenConfig:
        """
        Конфигурация экрана результата (заголовок, интервал опроса).
        Переопределить для включения автообновления.

        Пример с опросом каждые 5 секунд:
            return ResultScreenConfig(poll_interval_ms=5000, title="Статус деплоя")
        """
        return ResultScreenConfig()

    def get_result_status(self, environment: str, response: Any) -> ResultStatus:
        """
        Возвращает визуальный статус после первичного ответа сервера.
        По умолчанию — WAITING (форма находится в обработке).

        Переопределить, если начальный ответ может означать «ожидание»:
            if response.get("status") == "pending":
                return ResultStatus.WAITING
            return ResultStatus.SUCCESS
        """
        return ResultStatus.WAITING

    def get_poll_status(self, environment: str, poll_response: Any) -> ResultStatus:
        """
        Возвращает визуальный статус на основе ответа опроса.
        По умолчанию — WAITING (процесс ещё идёт).

        Переопределить для отображения финального состояния:
            status = poll_response.get("status", "")
            if status == "success":
                return ResultStatus.SUCCESS
            if status == "error":
                return ResultStatus.ERROR
            return ResultStatus.WAITING
        """
        return ResultStatus.WAITING

    def build_result_content(self, environment: str, response: Any) -> str:
        """
        Форматирует ответ сервера для отображения на экране результата.
        Вызывается сразу после успешной отправки.

        Переопределить для кастомного отображения (статус, прогресс-бар и т.д.).
        """
        if response is None:
            return "Форма успешно отправлена."
        return json.dumps(response, ensure_ascii=False, indent=2)

    def get_poll_endpoint(self, environment: str, response: Any) -> Optional[str]:
        """
        Возвращает URL для периодического GET-опроса состояния.
        Вызывается только если get_result_config().poll_interval_ms задан.

        response — ответ первоначального POST/PUT (можно извлечь ID задачи и т.п.).
        Вернуть None или пустую строку — опрос не будет выполнен.
        """
        return None

    def should_continue_polling(self, _environment: str, _poll_response: Any) -> bool:
        """
        Возвращает True если опрос нужно продолжать, False — чтобы остановить.
        Вызывается после каждого успешного poll-запроса.

        По умолчанию опрос идёт бесконечно. Переопределить для завершения
        по условию из ответа:
            return poll_response.get("status") not in ("success", "error")
        """
        return True

    def build_poll_content(self, environment: str, poll_response: Any) -> str:
        """
        Форматирует ответ опроса для отображения на экране результата.
        Вызывается после каждого успешного poll-запроса.

        Переопределить для извлечения нужных полей из ответа.
        """
        if poll_response is None:
            return ""
        return json.dumps(poll_response, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def pre_submit(
        self,
        form_data: Dict[str, Any],
        payload: Dict[str, Any],
        environment: str,
    ) -> None:
        """
        Хук, вызываемый перед отправкой HTTP-запроса.
        Выполняется после валидации и сборки payload, но до вызова HttpClient.

        Параметры:
            form_data   — исходные значения полей формы: {field.key: value}.
                          Содержит только видимые поля (скрытые условные исключены).
                          Изменение этого словаря не влияет на payload — он уже собран.

            payload     — JSON-словарь, который будет отправлен на сервер.
                          Можно модифицировать «на месте» через payload.update(...)
                          или payload["key"] = value — изменения попадут в запрос.

            environment — ключ выбранного окружения, например "prod_int" или "test_ext".
                          Совпадает со значениями Environment.key из config/environments.py.

        Переопределить для любых побочных действий:
          — запись в файл / git commit / git push
          — логирование, нотификации
          — трансформация payload «на месте»
          — проверка внешних условий с выбросом исключения (отменит отправку)

        Если метод бросает исключение — сабмит прерывается,
        пользователю показывается диалог с текстом ошибки.
        """

    @staticmethod
    def collect_plural(form_data: Dict[str, Any], base_key: str) -> List[Any]:
        """
        Собирает все значения plural-группы по базовому ключу.

        Возвращает список непустых значений: сначала base_key, затем
        base_key_2, base_key_3, … — по порядку, пока ключи существуют.
        Пустые строки, None и пустые списки пропускаются.

        Использование в build_payload():
            files = self.collect_plural(form_data, "config_file")
            # → ["content1", "content2"]
        """
        results: List[Any] = []
        base_val = form_data.get(base_key)
        if base_val is not None and base_val != "" and base_val != []:
            results.append(base_val)
        i = 2
        while f"{base_key}_{i}" in form_data:
            val = form_data[f"{base_key}_{i}"]
            if val is not None and val != "" and val != []:
                results.append(val)
            i += 1
        return results

    def validate(self, form_data: Dict[str, Any]) -> List[str]:
        """
        Базовая валидация: проверяет обязательные поля.
        Возвращает список сообщений об ошибках (пустой — если всё ок).

        Переопределить для добавления кастомной валидации.
        """
        errors: List[str] = []
        for field_def in self.fields:
            if not field_def.required:
                continue
            value = form_data.get(field_def.key)
            if value is None or str(value).strip() == "":
                errors.append(f'Поле "{field_def.label}" обязательно для заполнения')
        return errors

    # ------------------------------------------------------------------
    # ITSM-интеграция
    # ------------------------------------------------------------------

    def get_custom_buttons(self) -> List[CustomButton]:
        """
        Возвращает список кастомных кнопок для футера формы.
        Кнопки отображаются правее стандартных (Отправить, Просмотр JSON, Подтянуть из заявки).

        handler вызывается на главном потоке с двумя аргументами:
          - environment: str — ключ текущего окружения
          - apply_form_data: Callable[[Dict], List[str]] — метод предзаполнения формы

        Для фоновых операций запускайте threading.Thread внутри handler.

        Пример:
            def get_custom_buttons(self):
                return [CustomButton(label="Заполнить", handler=self._on_fill)]

            def _on_fill(self, environment: str) -> None:
                # self.screen — FormScreen: parent для диалогов + apply_form_data
                name = ask_string(self.screen, "Введите имя", "Имя ресурса")
                if name:
                    self.screen.apply_form_data({"resource_name": name})
        """
        return []

    @property
    def itsm_support(self) -> bool:
        """
        Включает кнопку «Подтянуть из заявки» на экране формы.
        Переопределить вместе с fetch_from_itsm():
            @property
            def itsm_support(self) -> bool:
                return True
        """
        return False

    def fetch_from_itsm(self, environment: str, ticket_id: str) -> Dict[str, Any]:
        """
        Получает данные из ITSM-заявки и возвращает словарь {field_key: value}.
        Вызывается в фоновом потоке при нажатии кнопки «Подтянуть из заявки».

        ticket_id — номер заявки, введённый пользователем в диалоговом окне.

        Ключи словаря должны совпадать с ключами полей формы (field.key).
        Если ключ не найден среди полей — он игнорируется.

        Переопределить в конкретной форме:
            def fetch_from_itsm(self, environment: str, ticket_id: str) -> Dict[str, Any]:
                response = self.itsm_service.get_ticket(ticket_id, environment)
                return {"app_name": response["appName"], "env": response["targetEnv"]}
        """
        raise NotImplementedError("fetch_from_itsm не реализован для этой формы")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.form_id!r}>"
