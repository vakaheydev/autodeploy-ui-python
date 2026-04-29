"""
ui/dialogs.py — типовые диалоговые окна и UI-утилиты.

Все функции принимают parent-виджет и работают как модальные окна
(grab_set / transient), встроенные в тему приложения.

Публичное API:
    show_info(parent, title, body)          — информационное сообщение
    show_error(parent, title, body)         — сообщение об ошибке
    show_warning(parent, title, body)       — предупреждение
    show_confirm(parent, title, body) → bool — диалог «Да / Нет»
    show_text_viewer(parent, title, text)   — модальное окно с прокручиваемым текстом
    show_item_detail(parent, title, item, detail_keys) — карточка детали элемента справочника
"""
import tkinter as tk
from datetime import datetime
from tkinter import scrolledtext, ttk
from typing import Any, Dict, Optional

import ui.theme as theme


# -------------------------------------------------------------------------
# Внутренние хелперы
# -------------------------------------------------------------------------

def _make_dialog(
    parent: tk.Widget,
    title: str,
    min_width: int = 380,
    min_height: int = 140,
) -> tk.Toplevel:
    """Создаёт базовый Toplevel в стиле приложения."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=theme.C["bg"])
    dlg.resizable(False, False)
    dlg.minsize(min_width, min_height)
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()
    return dlg


def _center(dlg: tk.Toplevel) -> None:
    """Центрирует окно относительно родительского."""
    dlg.update_idletasks()
    parent = dlg.master
    if parent is None:
        return
    root = parent.winfo_toplevel()
    rx = root.winfo_x() + root.winfo_width() // 2
    ry = root.winfo_y() + root.winfo_height() // 2
    w = dlg.winfo_width()
    h = dlg.winfo_height()
    dlg.geometry(f"+{rx - w // 2}+{ry - h // 2}")


def _icon_label(parent: tk.Widget, icon: str, color: str) -> tk.Label:
    return tk.Label(
        parent, text=icon,
        font=("Segoe UI", 22), bg=theme.C["bg"], fg=color,
    )


def _body_label(parent: tk.Widget, text: str) -> tk.Label:
    return tk.Label(
        parent, text=text, wraplength=340,
        font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text"],
        justify=tk.LEFT,
    )


# -------------------------------------------------------------------------
# Информационное окно
# -------------------------------------------------------------------------

def show_info(parent: tk.Widget, title: str, body: str) -> None:
    """
    Показывает информационный диалог с кнопкой «ОК».

    Пример:
        show_info(self, "Успех", "Деплой успешно запущен.")
    """
    dlg = _make_dialog(parent, title)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=20, pady=(16, 8), fill=tk.BOTH, expand=True)

    row = tk.Frame(content, bg=theme.C["bg"])
    row.pack(fill=tk.X)

    _icon_label(row, "ℹ", theme.C["primary"]).pack(side=tk.LEFT, anchor="n", padx=(0, 12))
    _body_label(row, body).pack(side=tk.LEFT, fill=tk.X, expand=True)

    theme.separator(dlg, pady=6)
    ttk.Button(dlg, text="ОК", style="Primary.TButton",
               command=dlg.destroy).pack(pady=(0, 14))

    _center(dlg)
    dlg.wait_window()


# -------------------------------------------------------------------------
# Диалог ошибки
# -------------------------------------------------------------------------

def show_error(parent: tk.Widget, title: str, body: str) -> None:
    """
    Показывает диалог ошибки с кнопкой «ОК».

    Пример:
        show_error(self, "Ошибка отправки", result.message)
    """
    dlg = _make_dialog(parent, title)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=20, pady=(16, 8), fill=tk.BOTH, expand=True)

    row = tk.Frame(content, bg=theme.C["bg"])
    row.pack(fill=tk.X)

    _icon_label(row, "✕", theme.C["error"]).pack(side=tk.LEFT, anchor="n", padx=(0, 12))

    # Если текст длинный — делаем прокручиваемым
    if len(body) > 300 or "\n" in body:
        st = scrolledtext.ScrolledText(
            row, width=46, height=8, wrap=tk.WORD,
            font=theme.F["small"],
            bg=theme.C["surface"], fg=theme.C["text"],
            relief="flat", bd=0, padx=6, pady=4,
        )
        st.insert("1.0", body)
        st.config(state=tk.DISABLED)
        st.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    else:
        _body_label(row, body).pack(side=tk.LEFT, fill=tk.X, expand=True)

    theme.separator(dlg, pady=6)
    ttk.Button(dlg, text="ОК", style="Primary.TButton",
               command=dlg.destroy).pack(pady=(0, 14))

    _center(dlg)
    dlg.wait_window()


# -------------------------------------------------------------------------
# Предупреждение
# -------------------------------------------------------------------------

def show_warning(parent: tk.Widget, title: str, body: str) -> None:
    """
    Показывает диалог предупреждения с кнопкой «ОК».

    Пример:
        show_warning(self, "Внимание", "Не все поля заполнены.")
    """
    dlg = _make_dialog(parent, title)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=20, pady=(16, 8), fill=tk.BOTH, expand=True)

    row = tk.Frame(content, bg=theme.C["bg"])
    row.pack(fill=tk.X)

    _icon_label(row, "⚠", theme.C["warning"]).pack(side=tk.LEFT, anchor="n", padx=(0, 12))
    _body_label(row, body).pack(side=tk.LEFT, fill=tk.X, expand=True)

    theme.separator(dlg, pady=6)
    ttk.Button(dlg, text="ОК", style="Primary.TButton",
               command=dlg.destroy).pack(pady=(0, 14))

    _center(dlg)
    dlg.wait_window()


# -------------------------------------------------------------------------
# Диалог подтверждения
# -------------------------------------------------------------------------

def show_confirm(parent: tk.Widget, title: str, body: str) -> bool:
    """
    Показывает диалог «Да / Нет». Возвращает True если пользователь нажал «Да».

    Пример:
        if show_confirm(self, "Подтверждение", "Вы уверены?"):
            ...
    """
    result: list[bool] = [False]

    dlg = _make_dialog(parent, title)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=20, pady=(16, 8), fill=tk.BOTH, expand=True)

    row = tk.Frame(content, bg=theme.C["bg"])
    row.pack(fill=tk.X)

    _icon_label(row, "?", theme.C["text_muted"]).pack(side=tk.LEFT, anchor="n", padx=(0, 12))
    _body_label(row, body).pack(side=tk.LEFT, fill=tk.X, expand=True)

    theme.separator(dlg, pady=6)

    btn_row = tk.Frame(dlg, bg=theme.C["bg"])
    btn_row.pack(pady=(0, 14))

    def _yes():
        result[0] = True
        dlg.destroy()

    ttk.Button(btn_row, text="Да", style="Primary.TButton", command=_yes).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(btn_row, text="Нет", style="Secondary.TButton",
               command=dlg.destroy).pack(side=tk.LEFT)

    _center(dlg)
    dlg.wait_window()
    return result[0]


# -------------------------------------------------------------------------
# Просмотрщик текста / JSON
# -------------------------------------------------------------------------

def show_refresh_confirm(
    parent: tk.Widget,
    resource_label: str,
    cached_at: Dict[str, Optional[float]],
) -> bool:
    """
    Диалог подтверждения обновления кеша справочника.

    Показывает дату последнего обновления для каждого окружения и предлагает
    обновить или отменить.

    cached_at — словарь {environment: unix-timestamp или None если кеша нет}.
    Возвращает True если пользователь нажал «Обновить».

    Примеры:
        # одно окружение (форма)
        show_refresh_confirm(self, label, {env: app.reference_cache.get_timestamp(res, env)})

        # несколько окружений (поиск)
        show_refresh_confirm(self, label, {e: app.reference_cache.get_timestamp(res, e) for e in envs})
    """
    result: list[bool] = [False]

    dlg = _make_dialog(parent, "Обновление справочника", min_width=360, min_height=160)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=20, pady=(16, 8), fill=tk.BOTH, expand=True)

    # Название справочника
    tk.Label(
        content,
        text=resource_label,
        font=theme.F["h3"],
        bg=theme.C["bg"],
        fg=theme.C["text"],
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 10))

    # Блок с датами последнего обновления
    info_frame = tk.Frame(content, bg=theme.C["surface"], padx=12, pady=8)
    info_frame.pack(fill=tk.X)

    tk.Label(
        info_frame,
        text="Последнее обновление:",
        font=theme.F["small"],
        bg=theme.C["surface"],
        fg=theme.C["text_muted"],
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 4))

    for env, ts in cached_at.items():
        row = tk.Frame(info_frame, bg=theme.C["surface"])
        row.pack(fill=tk.X, pady=1)

        # Метка окружения
        tk.Label(
            row,
            text=env.upper().replace("_", " "),
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            width=14,
            anchor="w",
        ).pack(side=tk.LEFT)

        # Timestamp или заглушка
        if ts is not None:
            ts_text  = datetime.fromtimestamp(ts).strftime("%d.%m.%Y  %H:%M:%S")
            ts_color = theme.C["text"]
        else:
            ts_text  = "кеш отсутствует"
            ts_color = theme.C["text_muted"]

        tk.Label(
            row,
            text=ts_text,
            font=theme.F["body"],
            bg=theme.C["surface"],
            fg=ts_color,
            anchor="w",
        ).pack(side=tk.LEFT)

    theme.separator(dlg, pady=6)

    btn_row = tk.Frame(dlg, bg=theme.C["bg"])
    btn_row.pack(pady=(0, 14))

    def _confirm():
        result[0] = True
        dlg.destroy()

    ttk.Button(btn_row, text="Обновить", style="Primary.TButton",
               command=_confirm).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btn_row, text="Отмена", style="Secondary.TButton",
               command=dlg.destroy).pack(side=tk.LEFT)

    _center(dlg)
    dlg.wait_window()
    return result[0]


# -------------------------------------------------------------------------
# Диалог подтверждения сабмита
# -------------------------------------------------------------------------

def show_submit_confirm(parent: tk.Widget, form_title: str, body: str) -> bool:
    """
    Диалог подтверждения отправки формы.

    Показывает метод, URL, окружение и payload (или кастомный текст из
    form.build_confirm_text()), предлагает «Отправить» / «Отмена».

    Возвращает True если пользователь нажал «Отправить».

    Пример:
        if show_submit_confirm(self, self._form.title, confirm_text):
            ...
    """
    result: list[bool] = [False]

    dlg = tk.Toplevel(parent)
    dlg.title("Подтверждение отправки")
    dlg.configure(bg=theme.C["bg"])
    dlg.minsize(520, 380)
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()

    # Заголовок
    hdr = tk.Frame(dlg, bg=theme.C["bg"])
    hdr.pack(fill=tk.X, padx=16, pady=(14, 6))

    _icon_label(hdr, "⚠", theme.C["warning"]).pack(side=tk.LEFT, padx=(0, 10))
    tk.Label(
        hdr, text=form_title,
        font=theme.F["h2"], bg=theme.C["bg"], fg=theme.C["text"],
    ).pack(side=tk.LEFT)

    # Тело — прокручиваемый текст
    st = scrolledtext.ScrolledText(
        dlg, width=64, height=16, wrap=tk.WORD,
        font=theme.F["mono"],
        bg=theme.C["surface"], fg=theme.C["text"],
        relief="flat", bd=0, padx=10, pady=8,
    )
    st.insert("1.0", body)
    st.config(state=tk.DISABLED)
    st.pack(padx=12, pady=(0, 4), fill=tk.BOTH, expand=True)

    theme.separator(dlg, pady=6)

    btn_row = tk.Frame(dlg, bg=theme.C["bg"])
    btn_row.pack(pady=(0, 14))

    def _confirm():
        result[0] = True
        dlg.destroy()

    ttk.Button(btn_row, text="Отправить", style="Primary.TButton",
               command=_confirm).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btn_row, text="Отмена", style="Secondary.TButton",
               command=dlg.destroy).pack(side=tk.LEFT)

    _center(dlg)
    dlg.wait_window()
    return result[0]


# -------------------------------------------------------------------------
# Просмотрщик текста / JSON
# -------------------------------------------------------------------------

def show_text_viewer(
    parent: tk.Widget,
    title: str,
    text: str,
    width: int = 68,
    height: int = 22,
) -> None:
    """
    Открывает модальное окно с прокручиваемым текстом (JSON, лог и т.п.).

    Пример:
        show_text_viewer(self, "Ответ сервера", json.dumps(data, indent=2))
    """
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=theme.C["bg"])
    dlg.grab_set()
    dlg.minsize(540, 400)
    dlg.transient(parent.winfo_toplevel())

    tk.Label(
        dlg, text=title,
        font=theme.F["h2"], bg=theme.C["bg"], fg=theme.C["text"],
    ).pack(anchor=tk.W, padx=14, pady=(12, 6))

    st = scrolledtext.ScrolledText(
        dlg, width=width, height=height, wrap=tk.WORD,
        font=theme.F["mono"],
        bg=theme.C["surface"], fg=theme.C["text"],
        relief="flat", bd=0, padx=10, pady=8,
    )
    st.insert("1.0", text)
    st.config(state=tk.DISABLED)
    st.pack(padx=12, pady=(0, 8), fill=tk.BOTH, expand=True)

    ttk.Button(
        dlg, text="Закрыть", style="Secondary.TButton", command=dlg.destroy,
    ).pack(pady=(0, 12))

    _center(dlg)
    dlg.wait_window()


# -------------------------------------------------------------------------
# Карточка детали элемента справочника
# -------------------------------------------------------------------------

def show_item_detail(
    parent: tk.Widget,
    title: str,
    item: Dict[str, Any],
    detail_keys: tuple,
) -> None:
    """
    Показывает модальную карточку детали элемента справочника.

    detail_keys: если не пустой — показывает только эти поля в этом порядке.
                 если пустой — показывает все поля элемента.
    """
    keys = list(detail_keys) if detail_keys else list(item.keys())
    fields = [(k, str(item.get(k, ""))) for k in keys if k in item]

    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=theme.C["bg"])
    dlg.resizable(True, True)
    dlg.minsize(420, 180)
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()

    tk.Label(
        dlg, text=title,
        font=theme.F["h2"], bg=theme.C["bg"], fg=theme.C["text"],
    ).pack(anchor=tk.W, padx=16, pady=(12, 8))

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=16, pady=(0, 4), fill=tk.BOTH, expand=True)

    for key, value in fields:
        row = tk.Frame(
            content, bg=theme.C["surface"],
            highlightthickness=1, highlightbackground=theme.C["border"],
        )
        row.pack(fill=tk.X, pady=2)

        tk.Label(
            row, text=key,
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
            width=18, anchor="w",
        ).pack(side=tk.LEFT, padx=(10, 0), pady=5)

        val_var = tk.StringVar(value=value)
        val_entry = tk.Entry(
            row, textvariable=val_var,
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text"],
            relief="flat", highlightthickness=0,
            readonlybackground=theme.C["surface"],
            state="readonly",
        )
        val_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), pady=5)

        def _copy(v=value) -> None:
            dlg.clipboard_clear()
            dlg.clipboard_append(v)

        tk.Button(
            row, text="⎘",
            font=theme.F["small"],
            bg=theme.C["surface"], fg=theme.C["text_muted"],
            activebackground=theme.C["ghost_h"], activeforeground=theme.C["primary"],
            relief="flat", bd=0, cursor="hand2",
            command=_copy,
        ).pack(side=tk.RIGHT, padx=(0, 8), pady=5)

    theme.separator(dlg, pady=6)
    ttk.Button(
        dlg, text="Закрыть", style="Secondary.TButton", command=dlg.destroy,
    ).pack(pady=(0, 12))

    _center(dlg)
    dlg.wait_window()
