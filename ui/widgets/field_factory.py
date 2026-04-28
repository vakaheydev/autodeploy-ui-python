"""
FieldFactory — создаёт стилизованные виджеты по FieldDefinition.
"""
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

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

    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        on_toggle: Optional[Callable[[], None]] = None,
    ) -> None:
        self._label     = label
        self._checked   = False
        self._on_toggle = on_toggle

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
        if self._on_toggle is not None:
            self._on_toggle()

    def set(self, checked: bool) -> None:
        """Устанавливает состояние без вызова on_toggle-коллбэка."""
        if self._checked == checked:
            return
        self._checked = checked
        if checked:
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


class _SearchableSelectWidget:
    """
    Виджет одиночного выбора с поиском.
    Отображает строку поиска и прокручиваемый список — аналог MULTISELECT,
    но с одиночным выбором.
    """

    _HINT = "Начните вводить для поиска..."

    def __init__(
        self,
        parent: tk.Widget,
        labels: List[str],
        values: List[str],
        search_strings: List[str],
    ) -> None:
        self._labels = labels
        self._values = values
        self._search_strings = search_strings
        self._selected_idx: Optional[int] = None
        self._visible_indices: List[int] = list(range(len(labels)))
        self._change_callbacks: List[Callable[[], None]] = []

        # Внешний контейнер
        self.frame = tk.Frame(
            parent,
            bg=theme.C["input_bg"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )

        # Строка поиска
        search_bar = tk.Frame(self.frame, bg=theme.C["input_bg"])
        search_bar.pack(fill=tk.X, padx=8, pady=(6, 0))

        tk.Label(
            search_bar, text="🔍",
            font=theme.F["body"], bg=theme.C["input_bg"], fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT)

        self._search_var = tk.StringVar()
        self._search_entry = tk.Entry(
            search_bar, textvariable=self._search_var,
            bg=theme.C["input_bg"], fg=theme.C["text_muted"],
            insertbackground=theme.C["text"],
            relief="flat", bd=0,
            font=theme.F["body"],
            highlightthickness=0,
        )
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        self._search_var.set(self._HINT)

        self._search_entry.bind("<FocusIn>",  self._on_focus_in)
        self._search_entry.bind("<FocusOut>", self._on_focus_out)

        # Разделитель
        tk.Frame(self.frame, bg=theme.C["border"], height=1).pack(fill=tk.X, pady=(6, 0))

        # Listbox
        lb_frame = tk.Frame(self.frame, bg=theme.C["input_bg"])
        lb_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        scrollbar = tk.Scrollbar(lb_frame, orient=tk.VERTICAL)
        self._listbox = tk.Listbox(
            lb_frame,
            yscrollcommand=scrollbar.set,
            bg=theme.C["input_bg"],
            fg=theme.C["text"],
            selectbackground=theme.C["primary"],
            selectforeground="white",
            relief="flat", bd=0,
            font=theme.F["body"],
            activestyle="none",
            exportselection=False,
            height=6,
        )
        scrollbar.config(command=self._listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for lbl in labels:
            self._listbox.insert(tk.END, lbl)

        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._search_var.trace_add("write", self._apply_filter)

    def _on_focus_in(self, _) -> None:
        if self._search_var.get() == self._HINT:
            self._search_var.set("")
            self._search_entry.config(fg=theme.C["text"])

    def _on_focus_out(self, _) -> None:
        if not self._search_var.get():
            self._search_var.set(self._HINT)
            self._search_entry.config(fg=theme.C["text_muted"])

    def _apply_filter(self, *_) -> None:
        query = self._search_var.get()
        if query == self._HINT:
            query = ""
        query = query.strip().lower()

        self._listbox.delete(0, tk.END)
        self._visible_indices = []
        for i, (lbl, sstr) in enumerate(zip(self._labels, self._search_strings)):
            if not query or query in sstr:
                self._listbox.insert(tk.END, lbl)
                self._visible_indices.append(i)

        # Восстановить выделение если выбранный элемент ещё виден
        if self._selected_idx is not None and self._selected_idx in self._visible_indices:
            pos = self._visible_indices.index(self._selected_idx)
            self._listbox.selection_set(pos)

    def _on_select(self, _) -> None:
        sel = self._listbox.curselection()
        if sel:
            self._selected_idx = self._visible_indices[sel[0]]
            for cb in self._change_callbacks:
                cb()

    def on_change(self, callback: Callable[[], None]) -> None:
        """Регистрирует коллбэк, вызываемый при выборе элемента."""
        self._change_callbacks.append(callback)

    def set_value(self, value: str) -> None:
        """Программно выбирает элемент по значению."""
        try:
            idx = self._values.index(value)
        except ValueError:
            return
        self._selected_idx = idx
        if idx in self._visible_indices:
            pos = self._visible_indices.index(idx)
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(pos)
            self._listbox.see(pos)

    def get(self) -> str:
        if self._selected_idx is not None:
            return self._values[self._selected_idx]
        return ""


class _BlockWidget:
    """
    Группа вложенных полей (BLOCK).
    Поддерживает условную видимость sub-полей и возвращает Dict[str, Any] из .get().
    """

    def __init__(
        self,
        parent: tk.Widget,
        sub_fields: List[FieldDefinition],
        factory: "FieldFactory",
        ref_loader: Callable[[FieldDefinition], List[Dict]],
    ) -> None:
        self.frame = tk.Frame(
            parent,
            bg=theme.C["surface"],
            highlightthickness=1,
            highlightbackground=theme.C["border"],
            highlightcolor=theme.C["border_focus"],
        )

        self._sub_fields = sub_fields
        self._sub_widgets: Dict[str, "FieldWidget"] = {}
        self._sub_containers: Dict[str, tk.Frame] = {}

        for sub_field in sub_fields:
            outer = tk.Frame(self.frame, bg=theme.C["border"])
            inner = tk.Frame(outer, bg=theme.C["surface"])
            inner.pack(fill=tk.BOTH, padx=1, pady=1)
            self._sub_containers[sub_field.key] = outer

            label_row = tk.Frame(inner, bg=theme.C["surface"])
            label_row.pack(fill=tk.X, padx=10, pady=(6, 2))
            req = "  *" if sub_field.required else ""
            tk.Label(
                label_row,
                text=f"{sub_field.label}{req}",
                font=theme.F["small"],
                bg=theme.C["surface"],
                fg=theme.C["text_label"] if sub_field.required else theme.C["text_muted"],
            ).pack(side=tk.LEFT)

            ref_items = ref_loader(sub_field)
            fw = factory.create(inner, sub_field, ref_items, ref_loader=ref_loader)
            fw.widget.pack(fill=tk.X, padx=10, pady=(0, 8))
            self._sub_widgets[sub_field.key] = fw

            if sub_field.condition:
                outer.pack_forget()
            else:
                outer.pack(fill=tk.X, pady=2, padx=4)

        self._setup_conditions()

    def _setup_conditions(self) -> None:
        has_conditional = any(f.condition for f in self._sub_fields)
        if not has_conditional:
            return
        for fw in self._sub_widgets.values():
            widget = fw.widget
            if isinstance(widget, ttk.Combobox):
                widget.bind("<<ComboboxSelected>>", lambda *_: self._refresh_conditions())
            else:
                fw.bind_change(self._refresh_conditions)

    def _refresh_conditions(self) -> None:
        values = {key: fw.get() for key, fw in self._sub_widgets.items()}
        for sub_field in self._sub_fields:
            if not sub_field.condition:
                continue
            outer = self._sub_containers.get(sub_field.key)
            if outer is None:
                continue
            should_show = sub_field.condition(values)
            is_visible = bool(outer.winfo_manager())
            if should_show and not is_visible:
                outer.pack(fill=tk.X, pady=2, padx=4)
            elif not should_show and is_visible:
                outer.pack_forget()

    def get(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for key, fw in self._sub_widgets.items():
            outer = self._sub_containers.get(key)
            if outer and not outer.winfo_manager():
                continue
            data[key] = fw.get()
        return data

    def set(self, values: Any) -> None:
        if not isinstance(values, dict):
            return
        for key, value in values.items():
            fw = self._sub_widgets.get(key)
            if fw:
                fw.set(value)


class FieldWidget:
    """Обёртка над виджетом с унифицированным .get()/.set() и опциональным bind_change()."""

    def __init__(
        self,
        widget: tk.Widget,
        get_fn: Callable[[], Any],
        bind_change_fn: Optional[Callable[[Callable[[], None]], None]] = None,
        set_fn: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self.widget = widget
        self._get_fn = get_fn
        self._bind_change_fn = bind_change_fn
        self._set_fn = set_fn

    def get(self) -> Any:
        return self._get_fn()

    def set(self, value: Any) -> None:
        """Программно устанавливает значение поля. Игнорируется если set_fn не задана."""
        if self._set_fn is not None:
            self._set_fn(value)

    def bind_change(self, callback: Callable[[], None]) -> None:
        """Подписывается на изменение значения. Работает для SELECT с поиском."""
        if self._bind_change_fn is not None:
            self._bind_change_fn(callback)


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
        ref_loader: Optional[Callable[[FieldDefinition], List[Dict[str, Any]]]] = None,
    ) -> FieldWidget:
        items = reference_items or []
        _empty_loader: Callable[[FieldDefinition], List[Dict[str, Any]]] = lambda _: []
        loader = ref_loader or _empty_loader
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
            case FieldType.FILE:
                return self._create_file(parent, field_def)
            case FieldType.BLOCK:
                return self._create_block(parent, field_def, loader)
            case _:
                raise ValueError(f"Неизвестный тип поля: {field_def.field_type}")

    # ------------------------------------------------------------------

    def _create_text(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        var = tk.StringVar(value=str(field.default or ""))
        entry = tk.Entry(parent, textvariable=var, **_ENTRY_KWARGS)
        self._add_placeholder(entry, var, field.placeholder)

        def _set(value: Any) -> None:
            s = str(value) if value is not None else ""
            if s:
                var.set(s)
                entry.config(fg=theme.C["text"])
            elif field.placeholder:
                var.set(field.placeholder)
                entry.config(fg=theme.C["text_muted"])
            else:
                var.set("")

        return FieldWidget(entry, lambda: self._real_value(var, field.placeholder), set_fn=_set)

    def _create_textarea(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        text = tk.Text(parent, height=4, wrap=tk.WORD, **_ENTRY_KWARGS, padx=6, pady=6)
        if field.default:
            text.insert("1.0", str(field.default))

        def _set(value: Any) -> None:
            s = str(value) if value is not None else ""
            text.delete("1.0", tk.END)
            if s:
                text.insert("1.0", s)

        return FieldWidget(text, lambda: text.get("1.0", tk.END).strip(), set_fn=_set)

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

        if ref.search_keys:
            search_strings = [
                " ".join(
                    str(item.get(k, "")) for k in ref.search_keys if item.get(k) is not None
                ).lower()
                for item in items
            ]
        else:
            search_strings = [lbl.lower() for lbl in labels]

        w = _SearchableSelectWidget(parent, labels, values, search_strings)
        if field.default is not None:
            w.set_value(str(field.default))
        return FieldWidget(w.frame, w.get, bind_change_fn=w.on_change, set_fn=w.set_value)

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

        # --- Строка поиска ---
        search_bar = tk.Frame(frame, bg=theme.C["input_bg"])
        search_bar.pack(fill=tk.X, padx=8, pady=(6, 0))

        tk.Label(
            search_bar, text="🔍",
            font=theme.F["body"], bg=theme.C["input_bg"], fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT)

        search_var = tk.StringVar()
        if ref and ref.search_keys:
            hint = f"Поиск по {', '.join(ref.search_keys)}..."
        else:
            hint = "Поиск..."
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

        # --- Скроллируемый список чекбоксов ---
        _MAX_H = 220  # максимальная высота списка в пикселях

        list_canvas = tk.Canvas(
            frame,
            bg=theme.C["input_bg"],
            highlightthickness=0,
            height=_MAX_H,
        )
        list_scroll = tk.Scrollbar(frame, orient=tk.VERTICAL, command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=list_scroll.set)

        cb_container = tk.Frame(list_canvas, bg=theme.C["input_bg"])
        cb_win = list_canvas.create_window((0, 0), window=cb_container, anchor="nw")

        # Обновляем scrollregion и высоту canvas под реальный контент
        def _on_cb_configure(_):
            list_canvas.configure(scrollregion=list_canvas.bbox("all"))
            real_h = cb_container.winfo_reqheight()
            list_canvas.configure(height=min(real_h, _MAX_H))

        cb_container.bind("<Configure>", _on_cb_configure)

        # Растягиваем inner frame по ширине canvas
        def _on_canvas_resize(e):
            list_canvas.itemconfig(cb_win, width=e.width)

        list_canvas.bind("<Configure>", _on_canvas_resize)

        # Помечаем canvas как цель скролла — form_screen._route_mousewheel
        # обнаружит этот атрибут при движении колеса над любым дочерним виджетом
        list_canvas._scroll_target = list_canvas  # type: ignore[attr-defined]
        cb_container._scroll_target = list_canvas  # type: ignore[attr-defined]

        list_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=4)
        list_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4)

        # Данные строк: (_ToggleRow, value, search_string)
        rows: List[Tuple[_ToggleRow, str, str]] = []

        def _get_query() -> str:
            q = search_var.get()
            return "" if q == hint else q.strip().lower()

        def _render_rows(reset_scroll: bool = False) -> None:
            """Перерисовывает список: выбранные элементы — вверху, затем остальные."""
            query = _get_query()
            for toggle, _v, _s in rows:
                toggle.pack_forget()
            for toggle, _v, sstr in rows:
                if toggle.get() and (not query or query in sstr):
                    toggle.pack()
            for toggle, _v, sstr in rows:
                if not toggle.get() and (not query or query in sstr):
                    toggle.pack()
            if reset_scroll:
                list_canvas.yview_moveto(0)

        def _on_row_toggle() -> None:
            _render_rows()

        if display_labels:
            for dlabel, val, sstr in zip(display_labels, values, search_strings):
                toggle = _ToggleRow(cb_container, dlabel, on_toggle=_on_row_toggle)
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
        def _apply_filter(*_):
            _render_rows(reset_scroll=True)

        search_var.trace_add("write", _apply_filter)

        def get_selected() -> List[str]:
            return [val for toggle, val, _ in rows if toggle.get()]

        def set_selected(values_to_set: Any) -> None:
            target = set(values_to_set) if values_to_set else set()
            for toggle, val, _ in rows:
                toggle.set(val in target)
            _render_rows()

        if field.default is not None:
            set_selected(field.default)

        return FieldWidget(frame, get_selected, set_fn=set_selected)

    def _create_checkbox(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        var = tk.BooleanVar(value=bool(field.default))
        chk = ttk.Checkbutton(parent, variable=var, style="TCheckbutton")
        return FieldWidget(chk, var.get, set_fn=lambda v: var.set(bool(v)))

    def _create_number(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        var = tk.StringVar(value=str(field.default) if field.default is not None else "")
        vcmd = (parent.register(lambda v: v == "" or v.isdigit()), "%P")
        entry = tk.Entry(
            parent, textvariable=var,
            validate="key", validatecommand=vcmd,
            **_ENTRY_KWARGS,
        )
        return FieldWidget(
            entry,
            lambda: int(var.get()) if var.get().isdigit() else 0,
            set_fn=lambda v: var.set(str(int(v)) if v is not None and str(v).isdigit() else ""),
        )

    def _create_block(
        self,
        parent: tk.Widget,
        field: FieldDefinition,
        ref_loader: Callable[[FieldDefinition], List[Dict[str, Any]]],
    ) -> FieldWidget:
        block = _BlockWidget(parent, field.block_fields, self, ref_loader)
        return FieldWidget(block.frame, block.get, set_fn=block.set)

    def _create_file(self, parent: tk.Widget, field: FieldDefinition) -> FieldWidget:
        """
        Виджет типа FILE: кнопка «Выбрать файл» + textarea для ручного ввода/просмотра.
        .get() возвращает содержимое файла как строку.
        """
        frame = tk.Frame(
            parent,
            bg=theme.C["input_bg"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )

        # Панель с кнопкой выбора
        top_bar = tk.Frame(frame, bg=theme.C["input_bg"])
        top_bar.pack(fill=tk.X, padx=6, pady=(6, 0))

        ext = field.file_type or ""
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        btn_label = f"Выбрать файл  {ext}".strip() if ext else "Выбрать файл"

        text_widget = tk.Text(frame, height=5, wrap=tk.WORD, **_ENTRY_KWARGS, padx=6, pady=6)

        def _browse() -> None:
            filetypes: list[tuple[str, str]] = []
            if ext:
                filetypes.append((f"{ext} файлы", f"*{ext}"))
            filetypes.append(("Все файлы", "*.*"))
            path = filedialog.askopenfilename(
                title=f"Выберите файл — {field.label}",
                filetypes=filetypes,
            )
            if path:
                import pathlib
                content = pathlib.Path(path).read_text(encoding="utf-8")
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", content)

        tk.Button(
            top_bar,
            text=btn_label,
            font=theme.F["small"],
            bg=theme.C["input_bg"],
            fg=theme.C["primary"],
            activebackground=theme.C["ghost_h"],
            activeforeground=theme.C["primary"],
            relief="flat", bd=0, cursor="hand2",
            command=_browse,
        ).pack(side=tk.LEFT)

        tk.Frame(frame, bg=theme.C["border"], height=1).pack(fill=tk.X, pady=(4, 0))
        text_widget.pack(fill=tk.BOTH, padx=0, pady=0)

        if field.default:
            text_widget.insert("1.0", str(field.default))

        def _set(value: Any) -> None:
            s = str(value) if value is not None else ""
            text_widget.delete("1.0", tk.END)
            if s:
                text_widget.insert("1.0", s)

        return FieldWidget(frame, lambda: text_widget.get("1.0", tk.END).strip(), set_fn=_set)

    # ------------------------------------------------------------------
    # Плейсхолдер
    # ------------------------------------------------------------------

    @staticmethod
    def _add_placeholder(entry: tk.Entry, var: tk.StringVar, placeholder: str) -> None:
        if not placeholder:
            return
        # Устанавливаем плейсхолдер только если нет заранее заданного значения (default)
        if not var.get():
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
