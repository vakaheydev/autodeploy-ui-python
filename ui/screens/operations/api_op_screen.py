"""
ApiOpScreen — пример экрана операции со справочником АПИ.
"""
import tkinter as tk
from typing import Optional

import ui.theme as theme
from forms.fields import ReferenceConfig
from ui.dialogs import ask_dictionary, show_info
from ui.screens.base_screen import BaseScreen
from ui.screens.operations.op_utils import action_button, env_row, file_field, ref_field


_API_REF = ReferenceConfig(
    source="local",
    resource="gravitee_apis.json",
    value_key="id",
    label_key="name",
    search_keys=("name", "context_path", "id"),
)


class ApiOpScreen(BaseScreen):

    def _build(self) -> None:
        self._selected_api: Optional[str] = None

        self._add_back_button()
        self._add_title("Операция с АПИ")
        theme.separator(self, pady=8)

        env_row(self, self.app)
        self._api_label   = ref_field(self, "АПИ", self._pick_api)
        self._config_text = file_field(self, "Конфигурация (JSON)", file_type=".json")
        theme.separator(self, pady=10)
        self._run_btn = action_button(self, "Выполнить", self._run, state=tk.DISABLED)

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
            self._run_btn.config(state=tk.NORMAL)

    def _run(self) -> None:
        if not self._selected_api:
            return
        env    = self.app.current_environment.get()
        config = self._config_text.get("1.0", tk.END).strip()
        # TODO: реализовать логику операции
        show_info(self, "Готово", f"АПИ: {self._selected_api}\nОкружение: {env}\nКонфиг: {config[:80]}")
