"""
FormRegistry — реестр всех доступных форм (Singleton).

Использование:
    registry = FormRegistry()
    registry.register(MyForm())
    forms = registry.get_by_category("api")
"""
from typing import Dict, List

from forms.base_form import BaseForm


class FormRegistry:
    """
    Singleton-реестр форм.
    Является центральным местом хранения всех зарегистрированных форм.
    """

    _instance: "FormRegistry | None" = None
    _forms: Dict[str, BaseForm]

    def __new__(cls) -> "FormRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._forms = {}
        return cls._instance

    # ------------------------------------------------------------------
    # Регистрация
    # ------------------------------------------------------------------

    def register(self, form: BaseForm) -> None:
        """Регистрирует форму. Перезаписывает существующую с тем же form_id."""
        self._forms[form.form_id] = form

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def get(self, form_id: str) -> BaseForm:
        """Возвращает форму по ID. Raises KeyError если не найдена."""
        if form_id not in self._forms:
            raise KeyError(f"Форма '{form_id}' не зарегистрирована")
        return self._forms[form_id]

    def get_by_category(self, category: str) -> List[BaseForm]:
        """Возвращает все формы указанной категории (отсортированные по title)."""
        result = [f for f in self._forms.values() if f.category == category]
        return sorted(result, key=lambda f: f.title)

    def all_categories(self) -> List[str]:
        """Возвращает список уникальных категорий среди зарегистрированных форм."""
        return list({f.category for f in self._forms.values()})

    def all_forms(self) -> List[BaseForm]:
        return list(self._forms.values())

    def clear(self) -> None:
        """Очищает реестр (полезно в тестах)."""
        self._forms.clear()
