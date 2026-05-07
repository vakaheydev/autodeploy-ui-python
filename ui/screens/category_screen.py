"""
CategoryScreen — выбор категории и формы.
"""
import tkinter as tk
from tkinter import ttk

import ui.theme as theme
from config.categories import CATEGORIES, CATEGORY_ORDER
from forms.registry import FormRegistry
from ui.screens.base_screen import BaseScreen

# Иконка и цвет бейджа для каждой категории
_CAT_META = {
    "api":   ("⚡", theme.C["badge_api"],   "#1D4ED8"),
    "apps":  ("📦", theme.C["badge_apps"],  "#166534"),
    "other": ("📋", theme.C["badge_other"], "#92400E"),
}


class CategoryScreen(BaseScreen):

    def _build(self) -> None:
        self._add_back_button()

        self._title_lbl = self._add_title("Выберите категорию")

        _wrap = tk.Frame(self, bg=theme.C["bg"])
        _wrap.pack(fill=tk.BOTH, expand=True)
        self._content = self._centered_col(_wrap, max_width=760)

        self._show_categories()

    # ------------------------------------------------------------------
    # Уровень 1: категории
    # ------------------------------------------------------------------

    def _show_categories(self) -> None:
        self._clear()
        self._title_lbl.config(text="Выберите категорию")

        registry = FormRegistry()

        for cat_key in CATEGORY_ORDER:
            label = CATEGORIES.get(cat_key, cat_key)
            count = len(registry.get_by_category(cat_key))
            icon, badge_bg, badge_fg = _CAT_META.get(cat_key, ("•", theme.C["ghost_h"], theme.C["text"]))

            self._cat_row(cat_key, icon, label, count, badge_bg, badge_fg)

    def _cat_row(
        self, key: str, icon: str, label: str, count: int, badge_bg: str, badge_fg: str
    ) -> None:
        """Строка-карточка категории с иконкой и счётчиком."""
        border = tk.Frame(self._content, bg=theme.C["border"])
        border.pack(fill=tk.X, pady=3, padx=2)
        row = tk.Frame(border, bg=theme.C["surface"], cursor="hand2")
        row.pack(fill=tk.BOTH, padx=1, pady=1)

        # Левая часть
        left = tk.Frame(row, bg=theme.C["surface"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=14, pady=10)

        tk.Label(
            left, text=f"{icon}  {label}",
            font=theme.F["h3"], bg=theme.C["surface"], fg=theme.C["text"],
        ).pack(anchor=tk.W)

        tk.Label(
            left, text=f"{count} {'форма' if count == 1 else 'формы' if 2 <= count <= 4 else 'форм'}",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W)

        # Стрелка справа
        tk.Label(
            row, text="→",
            font=("Segoe UI", 13), bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(side=tk.RIGHT, padx=14)

        # Бейдж
        tk.Label(
            row, text=label.upper(),
            font=theme.F["small"], bg=badge_bg, fg=badge_fg,
            padx=7, pady=2,
        ).pack(side=tk.RIGHT, pady=10)

        # Hover
        def on_enter(e, f=row):
            self._set_bg(f, theme.C["ghost_h"])

        def on_leave(e, f=row):
            self._set_bg(f, theme.C["surface"])

        def on_click(e, k=key):
            self._show_forms(k)

        for w in (row, left) + tuple(left.winfo_children()) + tuple(row.winfo_children()):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

    # ------------------------------------------------------------------
    # Уровень 2: формы категории
    # ------------------------------------------------------------------

    def _show_forms(self, category: str) -> None:
        self._clear()
        cat_label = CATEGORIES.get(category, category)
        self._title_lbl.config(text=cat_label)

        # Кнопка «назад»
        ttk.Button(
            self._content,
            text="← Все категории",
            style="Ghost.TButton",
            command=self._show_categories,
        ).pack(anchor=tk.W, pady=(0, 8))

        registry = FormRegistry()
        forms = registry.get_by_category(category)

        if not forms:
            ttk.Label(
                self._content,
                text="Нет доступных форм в этой категории.",
                style="Muted.TLabel",
            ).pack(pady=24)
            return

        # --- Строка поиска ---
        search_frame = tk.Frame(
            self._content,
            bg=theme.C["input_bg"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )
        search_frame.pack(fill=tk.X, pady=(0, 8), padx=2)

        tk.Label(
            search_frame, text="🔍",
            font=theme.F["body"], bg=theme.C["input_bg"], fg=theme.C["text_muted"],
            padx=8,
        ).pack(side=tk.LEFT)

        _HINT = "Поиск по названию формы..."
        search_var = tk.StringVar(value=_HINT)
        search_entry = tk.Entry(
            search_frame, textvariable=search_var,
            bg=theme.C["input_bg"], fg=theme.C["text_muted"],
            insertbackground=theme.C["text"],
            relief="flat", bd=0, font=theme.F["body"],
            highlightthickness=0,
        )
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=7, padx=(0, 8))

        def _on_focus_in(_):
            if search_var.get() == _HINT:
                search_var.set("")
                search_entry.config(fg=theme.C["text"])

        def _on_focus_out(_):
            if not search_var.get():
                search_var.set(_HINT)
                search_entry.config(fg=theme.C["text_muted"])

        search_entry.bind("<FocusIn>",  _on_focus_in)
        search_entry.bind("<FocusOut>", _on_focus_out)

        # --- Карточки форм с фильтрацией ---
        form_rows: list[tuple] = []   # (border_frame, form)

        for form in forms:
            border = self._form_row(form)
            form_rows.append((border, form))

        def _apply_filter(*_):
            query = search_var.get()
            if query == _HINT:
                query = ""
            query = query.strip().lower()
            for border, form in form_rows:
                if not query or query in form.title.lower():
                    border.pack(fill=tk.X, pady=3, padx=2)
                else:
                    border.pack_forget()

        search_var.trace_add("write", _apply_filter)

    def _form_row(self, form) -> tk.Frame:
        border = tk.Frame(self._content, bg=theme.C["border"])
        border.pack(fill=tk.X, pady=3, padx=2)
        row = tk.Frame(border, bg=theme.C["surface"], cursor="hand2")
        row.pack(fill=tk.BOTH, padx=1, pady=1)

        tk.Label(
            row, text=form.title,
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text"],
        ).pack(side=tk.LEFT, padx=14, pady=10)

        tk.Label(
            row, text="→",
            font=("Segoe UI", 12), bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(side=tk.RIGHT, padx=14)

        def on_enter(e, f=row):
            self._set_bg(f, theme.C["ghost_h"])

        def on_leave(e, f=row):
            self._set_bg(f, theme.C["surface"])

        def on_click(e, fid=form.form_id):
            self._open_form(fid)

        for w in (row,) + tuple(row.winfo_children()):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

        return border

    # ------------------------------------------------------------------

    def _open_form(self, form_id: str) -> None:
        from ui.screens.form_screen import FormScreen
        self.app.navigate_to(FormScreen, form_id=form_id)

    def _clear(self) -> None:
        for w in self._content.winfo_children():
            w.destroy()

    @staticmethod
    def _set_bg(frame: tk.Frame, color: str) -> None:
        """Рекурсивно меняет фон фрейма и всех дочерних виджетов."""
        try:
            frame.config(bg=color)
            for child in frame.winfo_children():
                try:
                    child.config(bg=color)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
