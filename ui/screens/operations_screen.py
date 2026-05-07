"""
OperationsScreen — список операций.

Как добавить новую операцию:
  1. Создать экран в ui/screens/operations/my_op_screen.py (наследник BaseScreen)
  2. Добавить карточку в _OPERATIONS и импорт в _open()
"""
import tkinter as tk
from typing import Callable, List, Tuple

import ui.theme as theme
from ui.screens.base_screen import BaseScreen

# (icon, title, description, key)
_OPERATIONS: List[Tuple[str, str, str, str]] = [
    ("⚡", "Операция с АПИ", "Выбрать АПИ и выполнить действие", "api_op"),
]


class OperationsScreen(BaseScreen):

    def _build(self) -> None:
        self._add_back_button()
        self._add_title("Операции")
        theme.separator(self, pady=8)

        _wrap = tk.Frame(self, bg=theme.C["bg"])
        _wrap.pack(fill=tk.BOTH, expand=True)
        col = self._centered_col(_wrap, max_width=760)

        if not _OPERATIONS:
            self._build_empty(col)
            return

        cards_row = tk.Frame(col, bg=theme.C["bg"])
        cards_row.place(relx=0.5, rely=0.45, anchor="center")

        for i, (icon, title, desc, key) in enumerate(_OPERATIONS):
            if i > 0:
                tk.Frame(cards_row, bg=theme.C["bg"], width=20).pack(side=tk.LEFT)
            self._op_card(cards_row, icon, title, desc, lambda k=key: self._open(k))

    def _build_empty(self, parent: tk.Widget) -> None:
        tk.Label(
            parent, text="📋",
            font=("Segoe UI Emoji", 40),
            bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack(pady=(40, 8))
        tk.Label(
            parent, text="Раздел в разработке",
            font=theme.F["h2"],
            bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack()
        tk.Label(
            parent, text="Добавьте операции в _OPERATIONS в operations_screen.py",
            font=theme.F["small"],
            bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack(pady=(6, 0))

    def _op_card(
        self,
        parent: tk.Frame,
        icon: str,
        title: str,
        desc: str,
        on_click: Callable[[], None],
    ) -> None:
        border = tk.Frame(parent, bg=theme.C["border"])
        border.pack(side=tk.LEFT)

        card = tk.Frame(border, bg=theme.C["surface"], cursor="hand2", width=200, height=160)
        card.pack(padx=1, pady=1)
        card.pack_propagate(False)

        inner = tk.Frame(card, bg=theme.C["surface"])
        inner.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            inner, text=icon,
            font=("Segoe UI Emoji", 28),
            bg=theme.C["surface"], fg=theme.C["text"],
        ).pack()
        tk.Label(
            inner, text=title,
            font=theme.F["h2"],
            bg=theme.C["surface"], fg=theme.C["text"],
        ).pack(pady=(4, 0))
        tk.Label(
            inner, text=desc,
            font=theme.F["small"],
            bg=theme.C["surface"], fg=theme.C["text_muted"],
            wraplength=170, justify="center",
        ).pack()

        def _enter(e): self._set_bg(card, theme.C["ghost_h"])
        def _leave(e): self._set_bg(card, theme.C["surface"])
        def _click(e): on_click()

        for w in (card, inner) + tuple(inner.winfo_children()):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
            w.bind("<Button-1>", _click)

    def _open(self, key: str) -> None:
        if key == "api_op":
            from ui.screens.operations.api_op_screen import ApiOpScreen
            self.app.navigate_to(ApiOpScreen)

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
