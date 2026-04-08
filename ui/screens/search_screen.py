"""
SearchScreen — лендинг выбора раздела поиска.
Две большие карточки по центру: АПИ и Приложения.
"""
import tkinter as tk

import ui.theme as theme
from forms.fields import ReferenceConfig
from ui.screens.base_screen import BaseScreen


class SearchScreen(BaseScreen):

    def _build(self) -> None:
        self._add_back_button()
        self._add_title("Поиск")

        # Центрирующий контейнер
        center = tk.Frame(self, bg=theme.C["bg"])
        center.pack(expand=True, fill=tk.BOTH)

        cards_row = tk.Frame(center, bg=theme.C["bg"])
        cards_row.place(relx=0.5, rely=0.45, anchor="center")

        self._choice_card(
            cards_row,
            icon="⚡",
            title="АПИ",
            desc="Поиск по Gravitee API",
            ref=ReferenceConfig(
                source="local",
                resource="gravitee_apis.json",
                value_key="id",
                label_key="name",
                search_keys=("name", "context_path", "id"),
            ),
        )

        tk.Frame(cards_row, bg=theme.C["bg"], width=20).pack(side=tk.LEFT)

        self._choice_card(
            cards_row,
            icon="📦",
            title="Приложения",
            desc="Поиск по приложениям",
            ref=ReferenceConfig(
                source="http",
                resource="applications",
                value_key="id",
                label_key="name",
                search_keys=("name", "azp", "id"),
            ),
        )

    def _choice_card(
        self,
        parent: tk.Frame,
        icon: str,
        title: str,
        desc: str,
        ref: ReferenceConfig,
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
        ).pack()

        def on_enter(e):
            self._set_bg(card, theme.C["ghost_h"])

        def on_leave(e):
            self._set_bg(card, theme.C["surface"])

        def on_click(e):
            from ui.screens.search_detail_screen import SearchDetailScreen
            self.app.navigate_to(SearchDetailScreen, title=title, icon=icon, ref=ref)

        for w in (card, inner) + tuple(inner.winfo_children()):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

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
