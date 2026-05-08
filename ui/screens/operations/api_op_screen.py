"""
ApiOpScreen — пример экрана операции со справочниками АПИ и его методов.

Демонстрирует паттерн зависимого справочника:
  1. Сначала выбирается АПИ (ref_field)
  2. После выбора АПИ активируется кнопка выбора метода (dependent_ref_field)
  3. При открытии справочника методов api_id передаётся через extra_params
"""
import tkinter as tk
from typing import Optional

import ui.theme as theme
from forms.fields import ReferenceConfig
from ui.dialogs import ask_dictionary, show_info
from ui.screens.base_screen import BaseScreen
from ui.screens.operations.op_utils import (
    action_button, dependent_ref_field, env_row, file_field, ref_field,
)


_API_REF = ReferenceConfig(
    source="local",
    resource="gravitee_apis.json",
    value_key="id",
    label_key="name",
    search_keys=("name", "context_path", "id"),
)

# URL-шаблон содержит {api_id} — подставляется через extra_params
_API_METHODS_REF = ReferenceConfig(
    source="http",
    resource="gravitee_api_methods",
    value_key="id",
    label_key="name",
    required_params=("api_id",),
)


class ApiOpScreen(BaseScreen):

    def _build(self) -> None:
        self._selected_api: Optional[str] = None
        self._selected_method: Optional[str] = None

        self._add_back_button()
        self._add_title("Операция с АПИ")
        theme.separator(self, pady=8)

        _wrap = tk.Frame(self, bg=theme.C["bg"])
        _wrap.pack(fill=tk.BOTH, expand=True)
        col = self._centered_col(_wrap, max_width=760)

        env_row(col, self.app)
        self._api_label = ref_field(col, "АПИ", self._pick_api)

        # Кнопка отключена — активируется после выбора АПИ
        self._method_label, self._method_btn = dependent_ref_field(
            col, "Метод АПИ", self._pick_method,
        )

        self._config_text = file_field(col, "Конфигурация (JSON)", file_type=".json")
        theme.separator(col, pady=10)
        self._run_btn = action_button(col, "Выполнить", self._run, state=tk.DISABLED)

    def _pick_api(self) -> None:
        api_id = ask_dictionary(
            self, "Выбрать АПИ",
            reference=_API_REF,
            environment=self.app.current_environment.get(),
            app=self.app,
        )
        if api_id is not None:
            self._selected_api = api_id
            self._api_label.config(text=api_id, fg=theme.C["text"])
            # Сбрасываем зависимый выбор при смене АПИ
            self._selected_method = None
            self._method_label.config(text="— не выбрано —", fg=theme.C["text_muted"])
            self._method_btn.config(state=tk.NORMAL)
            self._run_btn.config(state=tk.DISABLED)

    def _pick_method(self) -> None:
        if not self._selected_api:
            return
        method_id = ask_dictionary(
            self, "Выбрать метод",
            reference=_API_METHODS_REF,
            environment=self.app.current_environment.get(),
            app=self.app,
            extra_params={"api_id": self._selected_api},
        )
        if method_id is not None:
            self._selected_method = method_id
            self._method_label.config(text=method_id, fg=theme.C["text"])
            self._run_btn.config(state=tk.NORMAL)

    def _run(self) -> None:
        if not self._selected_api:
            return
        env    = self.app.current_environment.get()
        config = self._config_text.get("1.0", tk.END).strip()
        # TODO: реализовать логику операции
        show_info(
            self, "Готово",
            f"АПИ: {self._selected_api}\n"
            f"Метод: {self._selected_method or '—'}\n"
            f"Окружение: {env}\n"
            f"Конфиг: {config[:80]}",
        )
