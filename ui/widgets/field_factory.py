"""
FieldFactory — создаёт стилизованные виджеты по FieldDefinition.
"""
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Tuple

import ui.theme as theme
from forms.fields import FieldDefinition, FieldType


class _ToggleRow:
    """
    Строка мультиселекта с кастомным чекбоксом на базе tk.Button.
    Использует Unicode ☐ / ☑ вместо системного индикатора ttk,
    чтобы избежать крестика на Windows.
    """

    _OFF = "☐"
    _ON  = "☑"

    def __init__(self, parent: tk.Widget, label: str) -> None:
        self._label   = label
        self._checked = False

        self._btn = tk.Button(
            parent,
            text=f"  {self._OFF}  {label}",
            font=theme.F["body"],
            bg=theme.C["input_bg"],
            fg=theme.C["text"],
            activebackground=theme.C["ghost_h"],
            activeforeground=theme.C["text"],
            relief="flat", bd=0,
            anchor="w", cursor="hand2",
            command=self._toggle,
        )

    def _toggle(self) -> None:
        self._checked = not self._checked
        if self._checked:
            self._btn.config(
                text=f"  {self._ON}  {self._label}",
                fg=theme.C["primary"],
                bg=theme.C["badge_api"],
            )
        else:
            self._btn.config(
                text=f"  {self._OFF}  {self._label}",
                fg=theme.C["text"],
                bg=theme.C["input_bg"],
            )

    def get(self) -> bool:
        return self._checked

    # Проксируем pack/pack_forget для фильтрации
    def pack(self, **kwargs) -> None:
        self._btn.pack(fill=tk.X, padx=6, pady=2, **kwargs)

    def pack_forget(self) -> None:
        self._btn.pack_forget()


class FieldWidget:
    """Обёртка над виджетом с унифицированным .get()."""

    def __init__(self, widget: tk.Widget, get_fn: Callable[[], Any]) -> None:
        self.widget = widget
        self._get_fn = get_fn

    def get(self) -> Any:
        return self._get_fn()


# Общие параметры для tk.Entry / tk.Text
_ENTRY_KWARGS = dict(
    bg=theme.C["input_bg"],
    fg=theme.C["text"],
    insertbackground=theme.C["text"],
    relief="flat",
    highlightthickness=1,
    highlightbackground=theme.C["input_border"],
    highlightcolor=theme.C["border_focus"],
    font=theme.F["body"],
)


class FieldFactory:
    """Фабрика: FieldDefinition → FieldWidget."""

    def create(
        self,
        parent: tk.Widget,
        field_def: FieldDefinition,
        reference_items: List[Dict[str, Any]] | None = None,
    ) -> FieldWidget:
        items = reference_items or []
        match field_def.field_type:
            case FieldType.TEXT:
                return self._create_text(parent, field_def)
            case FieldType.TEXTAREA:
                return self._create_textarea(parent, field_def)
            case FieldType.SELECT:
                return self._create_select(parent, field_def, items)
            case FieldType.MULTISELECT:
                return self._create_multiselect(parent, field_def, items)
            case FieldType.CHECKBOX:
                return self._create_checkbox(parent, field_def)
            case FieldType.NUMBER:
                return self._create_number(parent, field_def)
            case _:
                raise ValueError(f"Неизвестный тип поля: {field_def.field_type}")

    # ------------------------------------------------------------------

    def _create_text(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        var = tk.StringVar(value=str(field.default or ""))
        entry = tk.Entry(parent, textvariable=var, **_ENTRY_KWARGS)
        self._add_placeholder(entry, var, field.placeholder)
        return FieldWidget(entry, lambda: self._real_value(var, field.placeholder))

    def _create_textarea(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        text = tk.Text(parent, height=4, wrap=tk.WORD, **_ENTRY_KWARGS, padx=6, pady=6)
        if field.default:
            text.insert("1.0", str(field.default))
        return FieldWidget(text, lambda: text.get("1.0", tk.END).strip())

    def _create_select(
        self, parent: tk.Widget, field: FieldDefinition, items: List[Dict[str, Any]]
    ) -> FieldWidget:
        ref = field.reference
        if ref is None:
            var = tk.StringVar()
            combo = ttk.Combobox(parent, textvariable=var, state="readonly")
            return FieldWidget(combo, var.get)

        labels = [str(item.get(ref.label_key, "")) for item in items]
        values = [str(item.get(ref.value_key, "")) for item in items]

        var = tk.StringVar()
        combo = ttk.Combobox(parent, textvariable=var, values=labels, state="readonly")

        def get_value() -> str:
            sel = var.get()
            return values[labels.index(sel)] if sel in labels else ""

        return FieldWidget(combo, get_value)

    def _create_multiselect(
        self, parent: tk.Widget, field: FieldDefinition, items: List[Dict[str, Any]]
    ) -> FieldWidget:
        """
        Список чекбоксов с живым поиском.

        Если ref.search_keys задан — строка отображения объединяет все указанные
        поля через « — », и поиск работает по каждому из них независимо.
        Отмеченные элементы остаются отмеченными при фильтрации.
        """
        ref = field.reference

        # --- Подготовка данных ---
        values: List[str] = []
        display_labels: List[str] = []
        search_strings: List[str] = []   # нижний регистр, для сравнения

        for item in items:
            val = str(item.get(ref.value_key, "")) if ref else ""
            values.append(val)

            if ref and ref.search_keys:
                parts = [str(item.get(k, "")) for k in ref.search_keys if item.get(k) is not None]
                display_labels.append("  —  ".join(parts))
                search_strings.append(" ".join(parts).lower())
            else:
                lbl = str(item.get(ref.label_key, "")) if ref else val
                display_labels.append(lbl)
                search_strings.append(lbl.lower())

        # --- Внешний контейнер ---
        frame = tk.Frame(
            parent,
            bg=theme.C["input_bg"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )

        # --- Строка поиска (только если search_keys задан) ---
        has_search = bool(ref and ref.search_keys)
        if has_search:
            search_bar = tk.Frame(frame, bg=theme.C["input_bg"])
            search_bar.pack(fill=tk.X, padx=8, pady=(6, 0))

            tk.Label(
                search_bar, text="🔍",
                font=theme.F["body"], bg=theme.C["input_bg"], fg=theme.C["text_muted"],
            ).pack(side=tk.LEFT)

            search_var = tk.StringVar()
            hint = f"Поиск по {', '.join(ref.search_keys)}..."
            search_entry = tk.Entry(
                search_bar, textvariable=search_var,
                bg=theme.C["input_bg"], fg=theme.C["text"],
                insertbackground=theme.C["text"],
                relief="flat", bd=0,
                font=theme.F["body"],
                highlightthickness=0,
            )
            search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

            # Плейсхолдер для строки поиска
            search_var.set(hint)
            search_entry.config(fg=theme.C["text_muted"])

            def _on_search_focus_in(_):
                if search_var.get() == hint:
                    search_var.set("")
                    search_entry.config(fg=theme.C["text"])

            def _on_search_focus_out(_):
                if not search_var.get():
                    search_var.set(hint)
                    search_entry.config(fg=theme.C["text_muted"])

            search_entry.bind("<FocusIn>",  _on_search_focus_in)
            search_entry.bind("<FocusOut>", _on_search_focus_out)

            # Разделитель под строкой поиска
            tk.Frame(frame, bg=theme.C["border"], height=1).pack(
                fill=tk.X, padx=0, pady=(6, 0)
            )

        # --- Список чекбоксов ---
        cb_container = tk.Frame(frame, bg=theme.C["input_bg"])
        cb_container.pack(fill=tk.X, pady=4)

        # Данные строк: (_ToggleRow, value, search_string)
        rows: List[Tuple[_ToggleRow, str, str]] = []

        if display_labels:
            for dlabel, val, sstr in zip(display_labels, values, search_strings):
                toggle = _ToggleRow(cb_container, dlabel)
                toggle.pack()
                rows.append((toggle, val, sstr))
        else:
            tk.Label(
                cb_container,
                text="Нет доступных элементов",
                font=theme.F["small"],
                bg=theme.C["input_bg"],
                fg=theme.C["text_muted"],
            ).pack(padx=10, pady=8)

        # --- Фильтрация ---
        if has_search:
            def _apply_filter(*_):
                query = search_var.get()
                if query == hint:
                    query = ""
                query = query.strip().lower()

                for toggle, _v, _s in rows:
                    toggle.pack_forget()
                for toggle, _v, sstr in rows:
                    if not query or query in sstr:
                        toggle.pack()

            search_var.trace_add("write", _apply_filter)

        # Нижний отступ
        tk.Frame(frame, bg=theme.C["input_bg"], height=4).pack()

        def get_selected() -> List[str]:
            return [val for toggle, val, _ in rows if toggle.get()]

        return FieldWidget(frame, get_selected)

    def _create_checkbox(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        var = tk.BooleanVar(value=bool(field.default))
        chk = ttk.Checkbutton(parent, variable=var, style="TCheckbutton")
        return FieldWidget(chk, var.get)

    def _create_number(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        var = tk.StringVar(value=str(field.default or ""))
        vcmd = (parent.register(lambda v: v == "" or v.isdigit()), "%P")
        entry = tk.Entry(
            parent, textvariable=var,
            validate="key", validatecommand=vcmd,
            **_ENTRY_KWARGS,
        )
        return FieldWidget(entry, lambda: int(var.get()) if var.get().isdigit() else 0)

    # ------------------------------------------------------------------
    # Плейсхолдер
    # ------------------------------------------------------------------

    @staticmethod
    def _add_placeholder(entry: tk.Entry, var: tk.StringVar, placeholder: str) -> None:
        if not placeholder:
            return
        var.set(placeholder)
        entry.config(fg=theme.C["text_muted"])

        def on_focus_in(_):
            if var.get() == placeholder:
                var.set("")
                entry.config(fg=theme.C["text"])

        def on_focus_out(_):
            if not var.get():
                var.set(placeholder)
                entry.config(fg=theme.C["text_muted"])

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    @staticmethod
    def _real_value(var: tk.StringVar, placeholder: str) -> str:
        val = var.get()
        return "" if val == placeholder else val
