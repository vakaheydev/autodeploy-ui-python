"""
ApiOpScreen — пример экрана операции со справочником АПИ.

Демонстрирует шаблон: выбор окружения из app.current_environment,
выбор АПИ через ask_dictionary, выполнение действия.
"""
import tkinter as tk
from tkinter import ttk
from typing import Optional

import ui.theme as theme
from forms.fields import ReferenceConfig
from ui.dialogs import ask_dictionary, show_info
from ui.screens.base_screen import BaseScreen


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

        # --- Текущее окружение (readonly) ---
        env_row = tk.Frame(self, bg=theme.C["bg"])
        env_row.pack(fill=tk.X, pady=(0, 12))

        tk.Label(
            env_row, text="Окружение:",
            font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text_label"],
        ).pack(side=tk.LEFT)
        tk.Label(
            env_row,
            textvariable=self.app.current_environment,
            font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(side=tk.LEFT, padx=(6, 0))

        # --- Выбор АПИ ---
        card = theme.card(self, pady=0)

        tk.Label(
            card, text="АПИ",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 4))

        api_row = tk.Frame(card, bg=theme.C["surface"])
        api_row.pack(fill=tk.X, padx=14, pady=(0, 10))

        self._api_label = tk.Label(
            api_row, text="— не выбрано —",
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_muted"],
            anchor="w",
        )
        self._api_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(
            api_row, text="Выбрать",
            style="Ghost.TButton",
            command=self._pick_api,
        ).pack(side=tk.RIGHT)

        theme.separator(self, pady=10)

        # --- Кнопка выполнения ---
        self._run_btn = ttk.Button(
            self, text="Выполнить",
            style="Primary.TButton",
            command=self._run,
            state=tk.DISABLED,
        )
        self._run_btn.pack(anchor=tk.W)

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
        env = self.app.current_environment.get()
        # TODO: реализовать логику операции
        show_info(self, "Готово", f"АПИ: {self._selected_api}\nОкружение: {env}")
