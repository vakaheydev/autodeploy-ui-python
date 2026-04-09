"""
BaseForm — абстрактный базовый класс для всех форм приложения.

Как добавить новую форму:
  1. Создать класс, унаследованный от BaseForm
  2. Реализовать все абстрактные свойства/методы
  3. Зарегистрировать экземпляр в forms/loader.py
"""
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from forms.fields import FieldDefinition
from forms.result_config import ResultScreenConfig


class BaseForm(ABC):
    """
    Декларативное описание формы.
    Знает о структуре данных, но НЕ знает об UI и HTTP деталях реализации.
    """

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

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.form_id!r}>"
