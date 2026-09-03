"""Немодальный индикатор фонового AI-flow с отменой."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

import ui.theme as theme


class AIProgressDialog:
    def __init__(self, parent: tk.Widget, on_cancel: Callable[[], None]) -> None:
        self._on_cancel = on_cancel
        self._dlg = tk.Toplevel(parent)
        self._dlg.title("AI-автозаполнение")
        self._dlg.configure(bg=theme.C["bg"])
        self._dlg.resizable(False, False)
        self._dlg.minsize(430, 170)
        self._dlg.transient(parent.winfo_toplevel())
        self._dlg.protocol("WM_DELETE_WINDOW", self.cancel)
        self._dlg.grab_set()

        tk.Label(
            self._dlg, text="OpenCode анализирует заявку",
            font=theme.F["h2"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(anchor=tk.W, padx=20, pady=(18, 6))
        self._status = tk.StringVar(value="Подготавливаю операцию...")
        tk.Label(
            self._dlg, textvariable=self._status,
            font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=20, pady=(0, 10))
        self._progress = ttk.Progressbar(self._dlg, mode="indeterminate", length=390)
        self._progress.pack(fill=tk.X, padx=20)
        self._progress.start(12)
        self._cancel_btn = ttk.Button(
            self._dlg, text="Отмена", style="Secondary.TButton", command=self.cancel,
        )
        self._cancel_btn.pack(anchor=tk.E, padx=20, pady=14)
        self._center(parent)

    @property
    def exists(self) -> bool:
        try:
            return bool(self._dlg.winfo_exists())
        except tk.TclError:
            return False

    def update_status(self, text: str) -> None:
        if self.exists:
            self._status.set(text)

    def cancel(self) -> None:
        if not self.exists or str(self._cancel_btn.cget("state")) == tk.DISABLED:
            return
        self._cancel_btn.config(state=tk.DISABLED)
        self._status.set("Отменяю операцию...")
        self._on_cancel()

    def close(self) -> None:
        if not self.exists:
            return
        self._progress.stop()
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()

    def _center(self, parent: tk.Widget) -> None:
        self._dlg.update_idletasks()
        root = parent.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - self._dlg.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self._dlg.winfo_reqheight()) // 2
        self._dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
