"""
SearchDetailScreen — экран поиска по конкретному разделу.

Структура:
  ← Назад   Заголовок
  [ENV PICKER — раскрывающийся бейдж]
  [  Поисковая строка (по центру)   ]
  Результаты
"""
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Tuple

import ui.theme as theme
from forms.fields import ReferenceConfig
from ui.screens.base_screen import BaseScreen

_TIERS: List[Tuple[str, str]] = [
    ("test",    "TEST"),
    ("regress", "REGRESS"),
    ("prod",    "PROD"),
    ("all",     "ALL"),
]

_NETS: List[Tuple[str, str]] = [
    ("int",  "INT"),
    ("ext",  "EXT"),
    ("both", "INT & EXT"),
]


def _resolve_envs(tier: str, net: str) -> List[str]:
    tiers = ["test", "regress", "prod"] if tier == "all" else [tier]
    nets  = ["int", "ext"]              if net  == "both" else [net]
    return [f"{t}_{n}" for t in tiers for n in nets]


def _env_label(tier: str, net: str) -> str:
    tier_labels = {"test": "TEST", "regress": "REGRESS", "prod": "PROD", "all": "ALL"}
    net_labels  = {"int": "INT", "ext": "EXT", "both": "INT & EXT"}
    return f"{tier_labels.get(tier, tier)}  ·  {net_labels.get(net, net)}"


class SearchDetailScreen(BaseScreen):

    def __init__(self, master, app, title: str, icon: str, ref: ReferenceConfig, **kwargs):
        self._section_title = title
        self._section_icon  = icon
        self._ref           = ref
        super().__init__(master, app, **kwargs)

    def _build(self) -> None:
        self._add_back_button()

        # Заголовок + кнопка обновления справочника (только для HTTP)
        header = tk.Frame(self, bg=theme.C["bg"])
        header.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            header,
            text=f"{self._section_icon}  {self._section_title}",
            style="H1.TLabel",
        ).pack(side=tk.LEFT)

        if self._ref.source == "http":
            self._refresh_btn = tk.Button(
                header,
                text="↻",
                font=theme.F["body"],
                bg=theme.C["bg"],
                fg=theme.C["primary"],
                activebackground=theme.C["bg"],
                activeforeground=theme.C["primary_h"],
                relief="flat", bd=0,
                cursor="hand2",
                command=self._on_refresh_click,
            )
            self._refresh_btn.pack(side=tk.LEFT, padx=(10, 0), pady=(4, 0))

        self._tier = tk.StringVar(value="test")
        self._net  = tk.StringVar(value="int")

        # --- Env picker + поиск по центру ---
        top_area = tk.Frame(self, bg=theme.C["bg"])
        top_area.pack(fill=tk.X, pady=(30, 0))

        search_block = tk.Frame(top_area, bg=theme.C["bg"])
        search_block.pack()  # без fill — центрируется горизонтально

        self._build_env_picker(search_block)
        self._build_search_bar(search_block)

        # --- Результаты внизу ---
        self._results_outer = tk.Frame(self, bg=theme.C["bg"])
        self._results_outer.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    # ------------------------------------------------------------------
    # Env picker
    # ------------------------------------------------------------------

    def _build_env_picker(self, parent: tk.Frame) -> None:
        self._picker_open = False

        # Бейдж-кнопка
        self._badge_border = tk.Frame(
            parent,
            bg=theme.C["input_border"],
        )
        self._badge_border.pack(pady=(0, 10))

        self._badge_frame = tk.Frame(self._badge_border, bg=theme.C["surface"], cursor="hand2")
        self._badge_frame.pack(padx=1, pady=1)

        self._badge_label = tk.Label(
            self._badge_frame,
            text=f"  {_env_label(self._tier.get(), self._net.get())}  ▾  ",
            font=theme.F["body"],
            bg=theme.C["surface"], fg=theme.C["text"],
            padx=6, pady=6,
        )
        self._badge_label.pack()

        # Панель выбора (изначально скрыта, пакуется под бейджем)
        self._picker_panel = tk.Frame(
            parent,
            bg=theme.C["surface"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
        )

        self._build_picker_panel()

        # Клик на бейдж
        for w in (self._badge_frame, self._badge_label):
            w.bind("<Button-1>", lambda e: self._toggle_picker())
            w.bind("<Enter>",    lambda e: self._badge_frame.config(bg=theme.C["ghost_h"]))
            w.bind("<Leave>",    lambda e: self._badge_frame.config(bg=theme.C["surface"]))

    def _build_picker_panel(self) -> None:
        p = self._picker_panel

        tk.Label(
            p, text="Среда",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 4))

        tier_row = tk.Frame(p, bg=theme.C["surface"])
        tier_row.pack(anchor=tk.W, padx=14, pady=(0, 8))
        self._tier_btns: List[tk.Button] = []
        for key, label in _TIERS:
            b = self._seg_btn(tier_row, label, lambda k=key: self._set_tier(k))
            b.pack(side=tk.LEFT)
            self._tier_btns.append(b)

        tk.Label(
            p, text="Тип сети",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(0, 4))

        net_row = tk.Frame(p, bg=theme.C["surface"])
        net_row.pack(anchor=tk.W, padx=14, pady=(0, 12))
        self._net_btns: List[tk.Button] = []
        for key, label in _NETS:
            b = self._seg_btn(net_row, label, lambda k=key: self._set_net(k))
            b.pack(side=tk.LEFT)
            self._net_btns.append(b)

        self._refresh_seg()

    @staticmethod
    def _seg_btn(parent: tk.Frame, label: str, cmd) -> tk.Button:
        return tk.Button(
            parent, text=label,
            font=theme.F["small"],
            relief="flat", bd=0,
            padx=12, pady=5,
            cursor="hand2",
            activebackground=theme.C["primary_h"],
            activeforeground=theme.C["primary_fg"],
            command=cmd,
        )

    def _toggle_picker(self) -> None:
        if self._picker_open:
            self._picker_panel.pack_forget()
            self._badge_label.config(
                text=f"  {_env_label(self._tier.get(), self._net.get())}  ▾  "
            )
        else:
            self._picker_panel.pack(before=self._badge_border, pady=(0, 6))
            self._badge_label.config(
                text=f"  {_env_label(self._tier.get(), self._net.get())}  ▴  "
            )
        self._picker_open = not self._picker_open

    def _set_tier(self, key: str) -> None:
        self._tier.set(key)
        self._refresh_seg()
        self._update_badge()
        self._rerun_search()

    def _set_net(self, key: str) -> None:
        self._net.set(key)
        self._refresh_seg()
        self._update_badge()
        self._rerun_search()

    def _refresh_seg(self) -> None:
        t, n = self._tier.get(), self._net.get()
        for (key, _), btn in zip(_TIERS, self._tier_btns):
            sel = key == t
            btn.config(
                bg=theme.C["primary"] if sel else theme.C["surface"],
                fg=theme.C["primary_fg"] if sel else theme.C["text"],
            )
        for (key, _), btn in zip(_NETS, self._net_btns):
            sel = key == n
            btn.config(
                bg=theme.C["primary"] if sel else theme.C["surface"],
                fg=theme.C["primary_fg"] if sel else theme.C["text"],
            )

    def _update_badge(self) -> None:
        arrow = "▴" if self._picker_open else "▾"
        self._badge_label.config(
            text=f"  {_env_label(self._tier.get(), self._net.get())}  {arrow}  "
        )

    # ------------------------------------------------------------------
    # Поисковая строка
    # ------------------------------------------------------------------

    def _build_search_bar(self, parent: tk.Frame) -> None:
        bar = tk.Frame(
            parent,
            bg=theme.C["input_bg"],
            highlightthickness=2,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )
        bar.pack(fill=tk.X, ipadx=4)

        tk.Label(
            bar, text="🔍",
            font=theme.F["h3"],
            bg=theme.C["input_bg"], fg=theme.C["text_muted"],
            padx=10,
        ).pack(side=tk.LEFT)

        _HINT = "Начните вводить..."
        self._search_var = tk.StringVar(value=_HINT)
        self._search_entry = tk.Entry(
            bar, textvariable=self._search_var,
            bg=theme.C["input_bg"], fg=theme.C["text_muted"],
            insertbackground=theme.C["text"],
            relief="flat", bd=0,
            font=("Segoe UI", 13),
            highlightthickness=0,
            width=36,
        )
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=10, padx=(0, 10))

        self._HINT = _HINT

        def on_focus_in(_):
            if self._search_var.get() == _HINT:
                self._search_var.set("")
                self._search_entry.config(fg=theme.C["text"])

        def on_focus_out(_):
            if not self._search_var.get():
                self._search_var.set(_HINT)
                self._search_entry.config(fg=theme.C["text_muted"])

        self._search_entry.bind("<FocusIn>",  on_focus_in)
        self._search_entry.bind("<FocusOut>", on_focus_out)
        self._search_after_id = None
        self._search_var.trace_add("write", lambda *_: self._schedule_search())

    # ------------------------------------------------------------------
    # Поиск и результаты
    # ------------------------------------------------------------------

    def _schedule_search(self) -> None:
        if self._search_after_id is not None:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(250, self._rerun_search)

    def _rerun_search(self) -> None:
        query = self._search_var.get()
        if not query or query == self._HINT:
            self._show_results([])
            return

        # Версия запроса — устаревшие фоновые потоки не перетрут свежие результаты
        self._search_version: int = getattr(self, "_search_version", 0) + 1
        version = self._search_version

        self._show_loading()

        envs = _resolve_envs(self._tier.get(), self._net.get())
        ref  = self._ref
        keys = ref.search_keys if ref.search_keys else (ref.label_key,)
        q    = query.strip().lower()

        def _worker() -> None:
            all_items: List[Tuple[str, Dict[str, Any]]] = []
            for env in envs:
                try:
                    for item in self.app.reference_resolver.resolve(ref, env):
                        all_items.append((env, item))
                except Exception:
                    pass

            # Фильтрация
            filtered = [
                (env, item) for env, item in all_items
                if any(q in str(item.get(k, "")).lower() for k in keys)
            ]

            # Дедупликация (env + value_key)
            seen: set = set()
            unique: List[Tuple[str, Dict[str, Any]]] = []
            for env, item in filtered:
                uid = (env, str(item.get(ref.value_key, "")))
                if uid not in seen:
                    seen.add(uid)
                    unique.append((env, item))

            self.after(0, lambda: self._on_search_done(unique, version))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_refresh_click(self) -> None:
        """Показывает дату кеша и по подтверждению инвалидирует его и перезапускает поиск."""
        from ui.dialogs import show_refresh_confirm

        resource = self._ref.resource
        envs = _resolve_envs(self._tier.get(), self._net.get())
        timestamps = {
            env: self.app.reference_cache.get_timestamp(resource, env)
            for env in envs
        }

        if not show_refresh_confirm(self, self._section_title, timestamps):
            return

        # Сбрасываем кеш для всех окружений этого ресурса
        self.app.reference_cache.invalidate(resource)
        # Перезапускаем поиск — фоновый поток загрузит свежие данные
        self._rerun_search()

    def _show_loading(self) -> None:
        """Показывает индикатор загрузки в зоне результатов."""
        for w in self._results_outer.winfo_children():
            w.destroy()
        tk.Label(
            self._results_outer,
            text="Загрузка…",
            font=theme.F["body"],
            bg=theme.C["bg"],
            fg=theme.C["text_muted"],
        ).pack(pady=20)

    def _on_search_done(
        self, results: List[Tuple[str, Dict[str, Any]]], version: int
    ) -> None:
        """Вызывается из главного потока когда фоновый поиск завершён."""
        if version != self._search_version:
            return  # пришёл устаревший результат — игнорируем
        self._show_results(results)

    def _show_results(self, results: List[Tuple[str, Dict[str, Any]]]) -> None:
        for w in self._results_outer.winfo_children():
            w.destroy()

        if not results:
            return

        # Скроллируемый список
        canvas = tk.Canvas(self._results_outer, bg=theme.C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(self._results_outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)

        inner = tk.Frame(canvas, bg=theme.C["bg"])
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width - 8))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ref = self._ref
        for env, item in results[:100]:
            self._result_row(inner, env, item, ref)

        if len(results) > 100:
            tk.Label(
                inner,
                text=f"… показаны первые 100 из {len(results)}",
                font=theme.F["small"], bg=theme.C["bg"], fg=theme.C["text_muted"],
            ).pack(anchor=tk.W, pady=(4, 0))

    def _result_row(self, parent, env: str, item: Dict[str, Any], ref: ReferenceConfig) -> None:
        border = tk.Frame(parent, bg=theme.C["border"], cursor="hand2")
        border.pack(fill=tk.X, pady=2, padx=2)
        row = tk.Frame(border, bg=theme.C["surface"], cursor="hand2")
        row.pack(fill=tk.BOTH, padx=1, pady=1)

        # Бейдж окружения пакуется ПЕРВЫМ (side=RIGHT), чтобы всегда получать приоритет
        env_badge = tk.Label(
            row,
            text=env.upper().replace("_", " "),
            font=theme.F["small"],
            bg=theme.C["badge_other"], fg="#92400E",
            padx=6, pady=2,
            cursor="hand2",
        )
        env_badge.pack(side=tk.RIGHT, padx=10, pady=6)

        left = tk.Frame(row, bg=theme.C["surface"], cursor="hand2")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=6)

        lbl_title = tk.Label(
            left, text=str(item.get(ref.label_key, "")),
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text"],
            cursor="hand2",
        )
        lbl_title.pack(anchor=tk.W)

        extras = [
            f"{k}: {item[k]}"
            for k in (ref.search_keys or ())
            if k != ref.label_key and item.get(k)
        ]
        lbl_extras = None
        if extras:
            lbl_extras = tk.Label(
                left, text="  ·  ".join(extras),
                font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
                cursor="hand2",
            )
            lbl_extras.pack(anchor=tk.W)

        # Hover + клик
        hover_widgets = [border, row, left, lbl_title, env_badge]
        if lbl_extras:
            hover_widgets.append(lbl_extras)

        def on_enter(_):
            for w in (border, row, left, lbl_title) + ((lbl_extras,) if lbl_extras else ()):
                w.config(bg=theme.C["ghost_h"])

        def on_leave(_):
            for w in (border, row, left, lbl_title) + ((lbl_extras,) if lbl_extras else ()):
                w.config(bg=theme.C["surface"])
            border.config(bg=theme.C["border"])

        def on_click(_, _item=item, _env=env):
            self._open_detail(_item, _env)

        for w in hover_widgets:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

    def _open_detail(self, item: Dict[str, Any], env: str) -> None:
        win = tk.Toplevel(self)
        win.title(str(item.get(self._ref.label_key, "Запись")))
        win.configure(bg=theme.C["bg"])
        win.resizable(True, True)
        win.minsize(420, 200)

        # Заголовок
        header = tk.Frame(win, bg=theme.C["bg"])
        header.pack(fill=tk.X, padx=16, pady=(14, 0))

        tk.Label(
            header,
            text=str(item.get(self._ref.label_key, "")),
            font=theme.F["h2"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(side=tk.LEFT)

        tk.Label(
            header,
            text=env.upper().replace("_", " "),
            font=theme.F["small"],
            bg=theme.C["badge_other"], fg="#92400E",
            padx=6, pady=2,
        ).pack(side=tk.RIGHT, pady=4)

        theme.separator(win, pady=8)

        # Прокручиваемая область с полями
        canvas = tk.Canvas(win, bg=theme.C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)

        inner = tk.Frame(canvas, bg=theme.C["bg"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=(0, 12))

        # Строки ключ-значение
        detail_keys = self._ref.detail_keys
        fields_iter = (
            [(k, item[k]) for k in detail_keys if k in item]
            if detail_keys
            else list(item.items())
        )
        for key, value in fields_iter:
            row_frame = tk.Frame(inner, bg=theme.C["bg"])
            row_frame.pack(fill=tk.X, pady=2, padx=8)

            tk.Label(
                row_frame, text=key,
                font=theme.F["small"], bg=theme.C["bg"], fg=theme.C["text_muted"],
                width=22, anchor=tk.E,
            ).pack(side=tk.LEFT, padx=(0, 10))

            val_str = str(value) if value is not None else ""

            val_entry = tk.Entry(
                row_frame,
                font=theme.F["body"],
                bg=theme.C["bg"], fg=theme.C["text"],
                insertbackground=theme.C["text"],
                relief="flat", bd=0,
                highlightthickness=0,
                readonlybackground=theme.C["bg"],
                state="readonly",
            )
            val_entry.config(state="normal")
            val_entry.insert(0, val_str)
            val_entry.config(state="readonly")
            val_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def _copy(v=val_str):
                win.clipboard_clear()
                win.clipboard_append(v)

            tk.Button(
                row_frame, text="⎘",
                font=("Segoe UI", 9),
                relief="flat", bd=0,
                padx=4, pady=0,
                cursor="hand2",
                bg=theme.C["bg"], fg=theme.C["text_muted"],
                activebackground=theme.C["ghost_h"],
                activeforeground=theme.C["text"],
                command=_copy,
            ).pack(side=tk.LEFT, padx=(4, 0))

        win.grab_set()
        win.focus_set()
