"""
RunsScreen — экран предыдущих запусков форм.

Показывает историю отправленных форм. Устаревшие записи (структура формы
изменилась) отображаются, но кнопка восстановления для них недоступна.
"""
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import ui.theme as theme
from core.run_storage import RunRecord
from ui.screens.base_screen import BaseScreen


def _is_stale(run: RunRecord) -> bool:
    """True если структура формы изменилась с момента запуска."""
    try:
        from forms.registry import FormRegistry
        form = FormRegistry().get(run.form_id)
        current = {f.key: f.field_type.value for f in form.fields}
        return current != run.fields_snapshot
    except Exception:
        return True


def _form_title(run: RunRecord) -> str:
    try:
        from forms.registry import FormRegistry
        return FormRegistry().get(run.form_id).title
    except Exception:
        return run.form_id


class RunsScreen(BaseScreen):

    def _build(self) -> None:
        self._add_back_button()

        header = tk.Frame(self, bg=theme.C["bg"])
        header.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            header, text="Предыдущие запуски",
            font=theme.F["h1"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(side=tk.LEFT)

        theme.separator(self, pady=6)

        runs = self.app.run_storage.load_all()

        if not runs:
            tk.Label(
                self, text="История запусков пуста",
                font=theme.F["body"], bg=theme.C["bg"], fg=theme.C["text_muted"],
            ).pack(pady=40)
            return

        container = tk.Frame(self, bg=theme.C["bg"])
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg=theme.C["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)

        inner = tk.Frame(canvas, bg=theme.C["bg"])
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width - 8))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for run in runs:
            stale = _is_stale(run)
            self._run_card(inner, run, stale)

    def _run_card(self, parent: tk.Frame, run: RunRecord, stale: bool) -> None:
        border = tk.Frame(parent, bg=theme.C["border"])
        border.pack(fill=tk.X, pady=4, padx=2)
        card = tk.Frame(border, bg=theme.C["surface"])
        card.pack(fill=tk.BOTH, padx=1, pady=1)

        # Верхняя строка: название + бейдж статуса
        top = tk.Frame(card, bg=theme.C["surface"])
        top.pack(fill=tk.X, padx=14, pady=(10, 4))

        tk.Label(
            top, text=_form_title(run),
            font=theme.F["h3"], bg=theme.C["surface"], fg=theme.C["text"],
        ).pack(side=tk.LEFT)

        badge_color = theme.C["error"] if stale else theme.C["success"]
        badge_text  = "Устарело"       if stale else "Актуально"
        theme.badge(top, badge_text, badge_color).pack(
            side=tk.LEFT, padx=(10, 0), anchor="center"
        )

        # Нижняя строка: детали + кнопка
        bottom = tk.Frame(card, bg=theme.C["surface"])
        bottom.pack(fill=tk.X, padx=14, pady=(0, 10))

        ts       = datetime.fromtimestamp(run.timestamp).strftime("%d.%m.%Y  %H:%M")
        env_text = run.environment.upper().replace("_", " ")
        tk.Label(
            bottom, text=f"{env_text}  ·  {ts}",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT, anchor="center")

        btn_style = "Secondary.TButton" if stale else "Primary.TButton"
        ttk.Button(
            bottom,
            text="Восстановить →",
            style=btn_style,
            state=tk.DISABLED if stale else tk.NORMAL,
            command=lambda r=run: self._restore(r),
        ).pack(side=tk.RIGHT)

        if stale:
            tk.Label(
                bottom, text="Структура формы изменилась",
                font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
            ).pack(side=tk.RIGHT, padx=(0, 8), anchor="center")

    def _restore(self, run: RunRecord) -> None:
        from ui.screens.form_screen import FormScreen
        self.app.current_environment.set(run.environment)
        self.app.navigate_to(
            FormScreen,
            form_id=run.form_id,
            initial_data=run.form_data,
        )
