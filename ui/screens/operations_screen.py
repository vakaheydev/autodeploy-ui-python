"""
OperationsScreen — раздел операций (в разработке).
"""
import tkinter as tk
from tkinter import ttk

import ui.theme as theme
from ui.screens.base_screen import BaseScreen


class OperationsScreen(BaseScreen):

    def _build(self) -> None:
        self._add_back_button()
        self._add_title("Операции")
        theme.separator(self, pady=8)

        tk.Label(
            self,
            text="📋",
            font=("Segoe UI Emoji", 40),
            bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack(pady=(40, 8))

        tk.Label(
            self,
            text="Раздел в разработке",
            font=theme.F["h2"],
            bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack()

        tk.Label(
            self,
            text="Разделы операций появятся здесь.",
            font=theme.F["small"],
            bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack(pady=(6, 0))
