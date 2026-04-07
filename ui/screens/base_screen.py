"""
BaseScreen — базовый класс для всех экранов.
"""
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

import ui.theme as theme

if TYPE_CHECKING:
    from ui.app import Application


class BaseScreen(tk.Frame):
    """Базовый экран. Наследники реализуют _build()."""

    def __init__(self, master: tk.Widget, app: "Application", **kwargs) -> None:
        super().__init__(master, bg=theme.C["bg"], **kwargs)
        self.app = app
        self._build()

    def _build(self) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Типовые элементы
    # ------------------------------------------------------------------

    def _add_back_button(self, text: str = "← Назад", command=None) -> ttk.Button:
        if command is None:
            command = self.app.go_back
        btn = ttk.Button(self, text=text, style="Ghost.TButton", command=command)
        btn.pack(anchor=tk.W, pady=(0, 8))
        return btn

    def _add_title(self, text: str) -> ttk.Label:
        lbl = ttk.Label(self, text=text, style="H1.TLabel")
        lbl.pack(anchor=tk.W, pady=(0, 6))
        return lbl

    def _add_separator(self) -> None:
        theme.separator(self, pady=6)
