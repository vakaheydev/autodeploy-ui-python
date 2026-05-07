"""
HomeScreen — главная страница Gravitee Admin UI.
Три модуля: Поиск, AutoDeploy UI, Операции.
"""
import tkinter as tk
from tkinter import ttk
from typing import Tuple

import ui.theme as theme
from ui.screens.base_screen import BaseScreen

_MODULES: list[Tuple[str, str, str, str]] = [
    ("🔍", "Поиск",         "Поиск по АПИ и приложениям",     "search"),
    ("🚀", "AutoDeploy UI", "Деплой и управление АПИ",         "autodeploy"),
    ("📋", "Операции",      "Прочие операции",       "operations"),
]


class HomeScreen(BaseScreen):

    def _build(self) -> None:
        # --- Шапка ---
        header = tk.Frame(self, bg=theme.C["bg"])
        header.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            header, text="Gravitee Admin UI",
            font=theme.F["h1"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(side=tk.LEFT)

        tk.Label(
            header, text="v0.1",
            font=theme.F["small"], bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT, padx=(8, 0), anchor="s", pady=(0, 3))

        ttk.Button(
            header, text="⚙  Настройки",
            style="Ghost.TButton",
            command=self._open_settings,
        ).pack(side=tk.RIGHT)

        theme.separator(self, pady=10)

        # --- Центрированные карточки модулей ---
        _wrap = tk.Frame(self, bg=theme.C["bg"])
        _wrap.pack(fill=tk.BOTH, expand=True)
        col = self._centered_col(_wrap, max_width=640)

        for icon, title, desc, module_key in _MODULES:
            self._module_card(col, icon, title, desc, module_key)

    def _module_card(self, parent: tk.Frame, icon: str, title: str, desc: str, key: str) -> None:
        border = tk.Frame(parent, bg=theme.C["border"])
        border.pack(fill=tk.X, pady=4, padx=2)
        row = tk.Frame(border, bg=theme.C["surface"], cursor="hand2")
        row.pack(fill=tk.BOTH, padx=1, pady=1)

        left = tk.Frame(row, bg=theme.C["surface"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=16, pady=14)

        tk.Label(
            left, text=f"{icon}  {title}",
            font=theme.F["h2"], bg=theme.C["surface"], fg=theme.C["text"],
        ).pack(anchor=tk.W)

        tk.Label(
            left, text=desc,
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, pady=(2, 0))

        tk.Label(
            row, text="→",
            font=("Segoe UI", 14), bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(side=tk.RIGHT, padx=16)

        def on_enter(e, f=row):
            self._set_bg(f, theme.C["ghost_h"])

        def on_leave(e, f=row):
            self._set_bg(f, theme.C["surface"])

        def on_click(e, k=key):
            self._open_module(k)

        for w in (row, left) + tuple(left.winfo_children()) + tuple(row.winfo_children()):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

    # ------------------------------------------------------------------

    def _open_module(self, key: str) -> None:
        if key == "search":
            from ui.screens.search_screen import SearchScreen
            self.app.navigate_to(SearchScreen)
        elif key == "autodeploy":
            from ui.screens.main_screen import MainScreen
            self.app.navigate_to(MainScreen)
        elif key == "operations":
            from ui.screens.operations_screen import OperationsScreen
            self.app.navigate_to(OperationsScreen)

    def _open_settings(self) -> None:
        from ui.screens.settings_screen import SettingsScreen
        self.app.navigate_to(SettingsScreen)

    @staticmethod
    def _set_bg(frame: tk.Frame, color: str) -> None:
        try:
            frame.config(bg=color)
            for child in frame.winfo_children():
                try:
                    child.config(bg=color)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
