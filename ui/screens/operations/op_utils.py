"""
Утилиты для построения UI на экранах операций.

Каждая функция создаёт типовой блок (карточку с заголовком + содержимым)
и пакует его в parent через pack(fill=X). Возвращает виджет для чтения значения.

Публичное API:
    env_row(parent, app)                       — строка текущего окружения (read-only)
    ref_field(parent, label, on_pick) → Label  — поле выбора из справочника
    file_field(parent, label, ...) → Text      — выбор файла + textarea для ручного ввода
    text_field(parent, label) → Entry          — однострочный ввод
    action_button(parent, text, command) → Button — кнопка основного действия
"""
from tkinter import filedialog, ttk
from typing import Callable
import tkinter as tk

import ui.theme as theme
from ui.dialogs import show_error


def env_row(parent: tk.Widget, app) -> None:
    """Строка «Окружение: test_int» — только для чтения."""
    row = tk.Frame(parent, bg=theme.C["bg"])
    row.pack(fill=tk.X, pady=(0, 12))
    tk.Label(
        row, text="Окружение:",
        font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text_label"],
    ).pack(side=tk.LEFT)
    tk.Label(
        row, textvariable=app.current_environment,
        font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text"],
    ).pack(side=tk.LEFT, padx=(6, 0))


def ref_field(
    parent: tk.Widget,
    label: str,
    on_pick: Callable[[], None],
) -> tk.Label:
    """
    Поле выбора элемента из справочника.

    Создаёт карточку: заголовок + метка выбранного значения + кнопка «Выбрать».
    Возвращает Label с текущим значением — обновлять через:
        lbl.config(text=selected_id, fg=theme.C["text"])
    При пустом состоянии: text="— не выбрано —", fg=theme.C["text_muted"]
    """
    card = theme.card(parent, pady=0)
    tk.Label(
        card, text=label,
        font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
    ).pack(anchor=tk.W, padx=14, pady=(10, 4))

    row = tk.Frame(card, bg=theme.C["surface"])
    row.pack(fill=tk.X, padx=14, pady=(0, 10))

    value_label = tk.Label(
        row, text="— не выбрано —",
        font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        anchor="w",
    )
    value_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    ttk.Button(row, text="Выбрать", style="Ghost.TButton", command=on_pick).pack(side=tk.RIGHT)

    return value_label


def file_field(
    parent: tk.Widget,
    label: str,
    file_type: str = ".json",
    height: int = 8,
) -> tk.Text:
    """
    Поле выбора файла + textarea для ручного ввода/вставки.

    Содержимое читать через: widget.get("1.0", tk.END).strip()

    Кнопка «📂 Выбрать файл» открывает диалог и загружает содержимое в textarea.
    Пользователь может также вставить или написать содержимое вручную.
    """
    ext = file_type if file_type.startswith(".") else f".{file_type}"

    card = theme.card(parent, pady=0)

    header = tk.Frame(card, bg=theme.C["surface"])
    header.pack(fill=tk.X, padx=14, pady=(10, 6))

    tk.Label(
        header, text=label,
        font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
    ).pack(side=tk.LEFT)

    def _browse() -> None:
        path = filedialog.askopenfilename(
            title=f"Выберите файл {ext}",
            filetypes=[(f"{ext.lstrip('.')} files", f"*{ext}"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            text_widget.delete("1.0", tk.END)
            text_widget.insert("1.0", content)
        except Exception as exc:
            show_error(parent, "Ошибка чтения файла", str(exc))

    ttk.Button(
        header, text="📂 Выбрать файл",
        style="Ghost.TButton", command=_browse,
    ).pack(side=tk.RIGHT)

    border = tk.Frame(card, bg=theme.C["input_border"])
    border.pack(fill=tk.X, padx=14, pady=(0, 10))

    text_widget = tk.Text(
        border,
        height=height,
        font=("Consolas", 10),
        bg=theme.C["input_bg"], fg=theme.C["text"],
        insertbackground=theme.C["text"],
        relief="flat", bd=0,
        wrap=tk.NONE,
        padx=8, pady=6,
    )
    text_widget.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

    return text_widget


def text_field(parent: tk.Widget, label: str) -> tk.Entry:
    """
    Однострочное текстовое поле.
    Значение читать через: entry.get().strip()
    """
    card = theme.card(parent, pady=0)
    tk.Label(
        card, text=label,
        font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
    ).pack(anchor=tk.W, padx=14, pady=(10, 4))

    entry = tk.Entry(
        card,
        bg=theme.C["input_bg"], fg=theme.C["text"],
        relief="solid", bd=1,
        font=theme.F["body"],
        insertbackground=theme.C["text"],
        highlightthickness=1,
        highlightbackground=theme.C["input_border"],
        highlightcolor=theme.C["border_focus"],
    )
    entry.pack(fill=tk.X, padx=14, pady=(0, 10))
    return entry


def action_button(
    parent: tk.Widget,
    text: str,
    command: Callable[[], None],
    state: str = tk.NORMAL,
) -> ttk.Button:
    """Основная кнопка действия (Primary.TButton). Выравнивается по левому краю."""
    btn = ttk.Button(parent, text=text, style="Primary.TButton", command=command, state=state)
    btn.pack(anchor=tk.W)
    return btn
