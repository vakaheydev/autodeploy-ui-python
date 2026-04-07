"""
BaseForm — абстрактный базовый класс для всех форм приложения.

Как добавить новую форму:
  1. Создать класс, унаследованный от BaseForm
  2. Реализовать все абстрактные свойства/методы
  3. Зарегистрировать экземпляр в forms/loader.py
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from forms.fields import FieldDefinition


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
