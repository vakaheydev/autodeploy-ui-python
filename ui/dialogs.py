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
    ask_string(parent, title, prompt, confirm_text) → Optional[str] — диалог ввода строки
    ask_dictionary(parent, title, reference, environment, app, ...) → Optional[str] — выбор одного элемента справочника
    ask_multi_dictionary(parent, title, reference, environment, app, ...) → Optional[List[str]] — выбор нескольких элементов справочника
    ask_ticket_id(parent) → Optional[str]  — диалог ввода номера ITSM-заявки
"""
import tkinter as tk
from datetime import datetime
from tkinter import scrolledtext, ttk
from typing import Any, Dict, List, Optional

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
# Универсальный диалог ввода строки
# -------------------------------------------------------------------------

def ask_string(
    parent: tk.Widget,
    title: str,
    prompt: str,
    confirm_text: str = "Подтвердить",
) -> Optional[str]:
    """
    Универсальный диалог ввода одной строки.
    Возвращает введённую строку или None если пользователь закрыл окно / нажал «Отмена».

    Параметры:
        title        — заголовок окна
        prompt       — текст-подсказка над полем ввода
        confirm_text — текст кнопки подтверждения (по умолчанию «Подтвердить»)

    Пример:
        name = ask_string(self, "Создать тег", "Введите имя тега", confirm_text="Создать")
        if name:
            ...
    """
    result: list[Optional[str]] = [None]

    dlg = _make_dialog(parent, title, min_width=340, min_height=120)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=20, pady=(16, 8), fill=tk.BOTH, expand=True)

    tk.Label(
        content, text=prompt,
        font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text"],
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 8))

    var = tk.StringVar()
    entry = tk.Entry(
        content, textvariable=var,
        font=theme.F["body"],
        bg=theme.C["input_bg"], fg=theme.C["text"],
        insertbackground=theme.C["text"],
        relief="flat",
        highlightthickness=1,
        highlightbackground=theme.C["input_border"],
        highlightcolor=theme.C["border_focus"],
    )
    entry.pack(fill=tk.X, ipady=4)

    theme.separator(dlg, pady=6)

    btn_row = tk.Frame(dlg, bg=theme.C["bg"])
    btn_row.pack(pady=(0, 14))

    def _confirm() -> None:
        val = var.get().strip()
        if val:
            result[0] = val
            dlg.destroy()

    entry.bind("<Return>", lambda _: _confirm())
    entry.bind("<KP_Enter>", lambda _: _confirm())

    ttk.Button(btn_row, text=confirm_text, style="Primary.TButton",
               command=_confirm).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btn_row, text="Отмена", style="Secondary.TButton",
               command=dlg.destroy).pack(side=tk.LEFT)

    _center(dlg)
    entry.focus_set()
    dlg.wait_window()
    return result[0]


# -------------------------------------------------------------------------
# Выбор элемента(ов) справочника
# -------------------------------------------------------------------------

_SEARCH_HINT = "Начните вводить для поиска..."


def _build_search_bar(parent: tk.Widget, on_change: Any) -> tk.StringVar:
    """Строка поиска с плейсхолдером. Возвращает StringVar с текущим запросом."""
    bar = tk.Frame(parent, bg=theme.C["input_bg"])
    bar.pack(fill=tk.X, padx=8, pady=6)

    tk.Label(
        bar, text="🔍",
        font=theme.F["body"], bg=theme.C["input_bg"], fg=theme.C["text_muted"],
    ).pack(side=tk.LEFT)

    var = tk.StringVar(value=_SEARCH_HINT)
    entry = tk.Entry(
        bar, textvariable=var,
        bg=theme.C["input_bg"], fg=theme.C["text_muted"],
        insertbackground=theme.C["text"],
        relief="flat", bd=0, font=theme.F["body"], highlightthickness=0,
    )
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

    def _focus_in(_):
        if var.get() == _SEARCH_HINT:
            var.set("")
            entry.config(fg=theme.C["text"])

    def _focus_out(_):
        if not var.get():
            var.set(_SEARCH_HINT)
            entry.config(fg=theme.C["text_muted"])

    entry.bind("<FocusIn>",  _focus_in)
    entry.bind("<FocusOut>", _focus_out)
    var.trace_add("write", on_change)
    return var


def _prep_items(
    items: List[Dict[str, Any]],
    value_key: str,
    label_key: str,
    search_keys: tuple,
) -> tuple:
    """Возвращает (values, labels, search_strings) для списка элементов справочника."""
    values: List[str] = [str(item.get(value_key, "")) for item in items]
    if search_keys:
        labels = [
            "  —  ".join(str(item.get(k, "")) for k in search_keys if item.get(k) is not None)
            for item in items
        ]
        search_strings = [
            " ".join(str(item.get(k, "")) for k in search_keys if item.get(k) is not None).lower()
            for item in items
        ]
    else:
        labels = [str(item.get(label_key, "")) for item in items]
        search_strings = [lbl.lower() for lbl in labels]
    return values, labels, search_strings


def ask_dictionary(
    parent: tk.Widget,
    title: str,
    reference: Any,
    environment: str,
    app: Any,
    confirm_text: str = "Выбрать",
) -> Optional[str]:
    """
    Диалог выбора одного элемента из справочника.

    Загружает данные через app.reference_resolver по правилам справочника (включая кеш).
    Параметры отображения (value_key, label_key, search_keys) берутся из reference.

    Параметры:
        reference    — ReferenceConfig с описанием справочника
        environment  — ключ окружения ("test_int", "prod_ext", …)
        app          — экземпляр Application (для resolver и cache)
        confirm_text — текст кнопки подтверждения

    Возвращает value_key выбранного элемента или None (отмена / закрытие).
    Двойной клик подтверждает выбор.

    Пример:
        from forms.fields import ReferenceConfig
        api_id = ask_dictionary(
            self.screen, "Выбрать АПИ",
            reference=ReferenceConfig(
                source="http", resource="gravitee_apis",
                value_key="id", label_key="name",
                search_keys=("name", "id", "context_path"),
            ),
            environment=environment,
            app=self.screen.app,
        )
        if api_id:
            ...
    """
    items = app.reference_resolver.resolve(reference, environment)
    result: list[Optional[str]] = [None]
    values, labels, search_strings = _prep_items(
        items, reference.value_key, reference.label_key, reference.search_keys or ()
    )

    dlg = _make_dialog(parent, title, min_width=460, min_height=360)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=16, pady=(14, 0), fill=tk.BOTH, expand=True)

    # Поле поиска
    search_outer = tk.Frame(
        content, bg=theme.C["input_bg"],
        highlightthickness=1,
        highlightbackground=theme.C["input_border"],
        highlightcolor=theme.C["border_focus"],
    )
    search_outer.pack(fill=tk.X, pady=(0, 4))

    visible: list[list[int]] = [list(range(len(labels)))]

    # Listbox
    lb_frame = tk.Frame(content, bg=theme.C["input_bg"])
    lb_frame.pack(fill=tk.BOTH, expand=True)

    sb = tk.Scrollbar(lb_frame, orient=tk.VERTICAL)
    listbox = tk.Listbox(
        lb_frame,
        yscrollcommand=sb.set,
        bg=theme.C["input_bg"], fg=theme.C["text"],
        selectbackground=theme.C["primary"], selectforeground="white",
        relief="flat", bd=0, font=theme.F["body"],
        activestyle="none", exportselection=False, height=12,
    )
    sb.config(command=listbox.yview)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    for lbl in labels:
        listbox.insert(tk.END, lbl)

    def _filter(*_) -> None:
        q = search_var.get()
        q = "" if q == _SEARCH_HINT else q.strip().lower()
        listbox.delete(0, tk.END)
        vis = []
        for i, (lbl, sstr) in enumerate(zip(labels, search_strings)):
            if not q or q in sstr:
                listbox.insert(tk.END, lbl)
                vis.append(i)
        visible[0] = vis

    search_var = _build_search_bar(search_outer, _filter)

    def _confirm() -> None:
        sel = listbox.curselection()
        if sel:
            result[0] = values[visible[0][sel[0]]]
            dlg.destroy()

    listbox.bind("<Double-Button-1>", lambda _: _confirm())

    theme.separator(dlg, pady=6)
    btn_row = tk.Frame(dlg, bg=theme.C["bg"])
    btn_row.pack(pady=(0, 14))

    ttk.Button(btn_row, text=confirm_text, style="Primary.TButton",
               command=_confirm).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btn_row, text="Отмена", style="Secondary.TButton",
               command=dlg.destroy).pack(side=tk.LEFT)

    _center(dlg)
    dlg.wait_window()
    return result[0]


def ask_multi_dictionary(
    parent: tk.Widget,
    title: str,
    reference: Any,
    environment: str,
    app: Any,
    confirm_text: str = "Выбрать",
) -> Optional[List[str]]:
    """
    Диалог выбора нескольких элементов из справочника.

    Загружает данные через app.reference_resolver (включая кеш).
    Параметры отображения берутся из reference.

    Возвращает список value_key выбранных элементов (может быть пустым если ничего не отмечено)
    или None (отмена / закрытие окна крестиком).

    Пример:
        from forms.fields import ReferenceConfig
        services = ask_multi_dictionary(
            self.screen, "Выбрать сервисы",
            reference=ReferenceConfig(
                source="http", resource="gravitee_services",
                value_key="id", label_key="name",
                search_keys=("name", "id"),
            ),
            environment=environment,
            app=self.screen.app,
        )
        if services is not None:   # None = отмена, [] = подтверждено без выбора
            ...
    """
    items = app.reference_resolver.resolve(reference, environment)
    result: list[Optional[List[str]]] = [None]
    values, labels, search_strings = _prep_items(
        items, reference.value_key, reference.label_key, reference.search_keys or ()
    )

    dlg = _make_dialog(parent, title, min_width=460, min_height=400)

    content = tk.Frame(dlg, bg=theme.C["bg"])
    content.pack(padx=16, pady=(14, 0), fill=tk.BOTH, expand=True)

    # Поле поиска
    search_outer = tk.Frame(
        content, bg=theme.C["input_bg"],
        highlightthickness=1,
        highlightbackground=theme.C["input_border"],
        highlightcolor=theme.C["border_focus"],
    )
    search_outer.pack(fill=tk.X, pady=(0, 4))

    # Скроллируемый список чекбоксов
    _MAX_H = 260
    list_canvas = tk.Canvas(content, bg=theme.C["input_bg"], highlightthickness=0, height=_MAX_H)
    list_sb = tk.Scrollbar(content, orient=tk.VERTICAL, command=list_canvas.yview)
    list_canvas.configure(yscrollcommand=list_sb.set)

    cb_frame = tk.Frame(list_canvas, bg=theme.C["input_bg"])
    cb_win = list_canvas.create_window((0, 0), window=cb_frame, anchor="nw")

    def _on_cb_configure(_):
        list_canvas.configure(scrollregion=list_canvas.bbox("all"))
        real_h = cb_frame.winfo_reqheight()
        list_canvas.configure(height=min(real_h + 4, _MAX_H))

    def _on_canvas_resize(e):
        list_canvas.itemconfig(cb_win, width=e.width)

    cb_frame.bind("<Configure>", _on_cb_configure)
    list_canvas.bind("<Configure>", _on_canvas_resize)
    list_canvas.bind_all("<MouseWheel>",
                         lambda e: list_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    list_sb.pack(side=tk.RIGHT, fill=tk.Y)
    list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # Строки чекбоксов
    _OFF, _ON = "☐", "☑"
    checked: List[bool] = [False] * len(items)
    row_btns: List[tk.Button] = []

    def _make_toggle(idx: int) -> tk.Button:
        def _toggle() -> None:
            checked[idx] = not checked[idx]
            if checked[idx]:
                btn.config(text=f"  {_ON}  {labels[idx]}",
                           fg=theme.C["primary"], bg=theme.C["badge_api"])
            else:
                btn.config(text=f"  {_OFF}  {labels[idx]}",
                           fg=theme.C["text"], bg=theme.C["input_bg"])

        btn = tk.Button(
            cb_frame,
            text=f"  {_OFF}  {labels[idx]}",
            font=theme.F["body"],
            bg=theme.C["input_bg"], fg=theme.C["text"],
            activebackground=theme.C["ghost_h"], activeforeground=theme.C["text"],
            relief="flat", bd=0, anchor="w", cursor="hand2",
            command=_toggle,
        )
        return btn

    for i in range(len(items)):
        btn = _make_toggle(i)
        btn.pack(fill=tk.X, padx=6, pady=2)
        row_btns.append(btn)

    def _filter(*_) -> None:
        q = search_var.get()
        q = "" if q == _SEARCH_HINT else q.strip().lower()
        for btn, sstr in zip(row_btns, search_strings):
            if not q or q in sstr:
                btn.pack(fill=tk.X, padx=6, pady=2)
            else:
                btn.pack_forget()

    search_var = _build_search_bar(search_outer, _filter)

    def _confirm() -> None:
        result[0] = [values[i] for i, c in enumerate(checked) if c]
        dlg.destroy()

    theme.separator(dlg, pady=6)
    btn_row = tk.Frame(dlg, bg=theme.C["bg"])
    btn_row.pack(pady=(0, 14))

    ttk.Button(btn_row, text=confirm_text, style="Primary.TButton",
               command=_confirm).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btn_row, text="Отмена", style="Secondary.TButton",
               command=dlg.destroy).pack(side=tk.LEFT)

    _center(dlg)
    dlg.wait_window()
    return result[0]


# -------------------------------------------------------------------------
# Ввод номера ITSM-заявки
# -------------------------------------------------------------------------

def ask_ticket_id(parent: tk.Widget) -> Optional[str]:
    """Диалог ввода номера ITSM-заявки. Обёртка над ask_string."""
    return ask_string(
        parent,
        title="Подтянуть из заявки",
        prompt="Введите номер заявки",
        confirm_text="Подтянуть",
    )


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
