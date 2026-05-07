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
        nav = tk.Frame(self, bg=theme.C["bg"])
        nav.pack(anchor=tk.W, pady=(0, 8))
        btn = ttk.Button(nav, text=text, style="Ghost.TButton", command=command)
        btn.pack(side=tk.LEFT)
        ttk.Button(nav, text="⌂ Домой", style="Ghost.TButton",
                   command=self.app.go_home).pack(side=tk.LEFT, padx=(4, 0))
        return btn

    def _add_title(self, text: str) -> ttk.Label:
        lbl = ttk.Label(self, text=text, style="H1.TLabel")
        lbl.pack(anchor=tk.W, pady=(0, 6))
        return lbl

    def _add_separator(self) -> None:
        theme.separator(self, pady=6)

    @staticmethod
    def _centered_col(parent: tk.Widget, max_width: int = 760) -> tk.Frame:
        """
        Создаёт Frame внутри parent, которая центрируется горизонтально и
        ограничивается по ширине при расширении окна.
        Используется на экранах без canvas (MainScreen, CategoryScreen и т.п.).
        """
        col = tk.Frame(parent, bg=theme.C["bg"])

        def _on_resize(e: tk.Event) -> None:
            w = min(e.width, max_width)
            col.place(relx=0.5, rely=0, anchor="n", width=w, relheight=1.0)

        parent.bind("<Configure>", _on_resize)
        return col

    @staticmethod
    def _centered_resize(canvas: tk.Canvas, win_id: int, max_width: int = 760, pad: int = 8):
        """
        Возвращает обработчик <Configure> для Canvas.
        Ограничивает ширину контента до max_width и центрирует его при широком окне.
        При ширине canvas < max_width контент заполняет всё доступное пространство.
        """
        def _handle(e: tk.Event) -> None:
            avail = e.width - pad
            w = min(avail, max_width)
            x = max(0, (avail - w) // 2)
            canvas.itemconfig(win_id, width=w)
            canvas.coords(win_id, x, 0)
        return _handle
