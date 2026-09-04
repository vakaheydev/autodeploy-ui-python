"""Современное интерактивное окно OpenCode session для одной заявки."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional

import ui.theme as theme
from opencode_integration.agent import ConversationEvent
from ui.chat_markdown import insert_markdown


class AIAssistantDialog:
    def __init__(
        self,
        parent: tk.Widget,
        *,
        mode: str = "research",
        thinking_level: str = "—",
        thinking_auto: bool = False,
        on_send: Callable[[str], None],
        on_finalize: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None],
        on_permission: Callable[[str, bool], None],
    ) -> None:
        if mode not in {"fill_only", "research"}:
            raise ValueError(f"Неизвестный режим помощника: {mode}")
        self._parent = parent
        self._mode = mode
        self._thinking_level = str(thinking_level).strip() or "—"
        self._thinking_auto = thinking_auto
        self._on_send = on_send
        self._on_finalize = on_finalize
        self._on_stop = on_stop
        self._on_cancel = on_cancel
        self._on_permission = on_permission
        self._permission_rows: Dict[str, tk.Frame] = {}
        self._answered_permissions: set[str] = set()
        self._cancelled = False
        self._spinner_after_id: Optional[str] = None
        self._spinner_angle = 0

        self._dlg = tk.Toplevel(parent)
        self._dlg.title("OpenCode — помощник заполнения формы")
        self._dlg.configure(bg=theme.C["bg"])
        self._dlg.geometry("980x700")
        self._dlg.minsize(780, 560)
        self._dlg.transient(parent.winfo_toplevel())
        self._dlg.protocol("WM_DELETE_WINDOW", self.cancel)
        self._build()
        self._dlg.grab_set()
        self._center()

    @property
    def exists(self) -> bool:
        try:
            return bool(self._dlg.winfo_exists())
        except tk.TclError:
            return False

    def _build(self) -> None:
        header = tk.Frame(self._dlg, bg=theme.C["bg"])
        header.pack(fill=tk.X, padx=20, pady=(16, 10))
        left = tk.Frame(header, bg=theme.C["bg"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            left,
            text="OpenCode Form Assistant",
            font=theme.F["h1"],
            bg=theme.C["bg"],
            fg=theme.C["text"],
        ).pack(anchor=tk.W)
        tk.Label(
            left,
            text=(
                (
                    "Быстрый режим: один прямой запрос заполнения, MCP отключены. "
                    if self._mode == "fill_only"
                    else "Режим исследования: видны сообщения, статусы и вызовы MCP. "
                )
                + "Внутренние скрытые рассуждения модели не отображаются."
            ),
            font=theme.F["small"],
            bg=theme.C["bg"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, pady=(2, 0))
        self._session_var = tk.StringVar(value="session: создаётся…")
        tk.Label(
            header,
            textvariable=self._session_var,
            font=("Consolas", 9),
            bg=theme.C["surface_alt"],
            fg=theme.C["text_muted"],
            padx=9,
            pady=5,
        ).pack(side=tk.RIGHT, anchor=tk.N)

        status_card = tk.Frame(self._dlg, bg=theme.C["border"])
        status_card.pack(fill=tk.X, padx=20, pady=(0, 10))
        status_inner = tk.Frame(status_card, bg=theme.C["surface"])
        status_inner.pack(fill=tk.X, padx=1, pady=1)
        status_line = tk.Frame(status_inner, bg=theme.C["surface"])
        status_line.pack(fill=tk.X, padx=10, pady=8)
        self._spinner = tk.Canvas(
            status_line,
            width=20,
            height=20,
            bg=theme.C["surface"],
            highlightthickness=0,
            bd=0,
        )
        self._spinner.pack(side=tk.LEFT, padx=(0, 8))
        self._status_var = tk.StringVar(value="Подготавливаю операцию…")
        self._status_label = tk.Label(
            status_line,
            textvariable=self._status_var,
            font=theme.F["body"],
            bg=theme.C["surface"],
            fg=theme.C["warning"],
            anchor="w",
        )
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        content = tk.PanedWindow(
            self._dlg,
            orient=tk.VERTICAL,
            bg=theme.C["border"],
            sashwidth=5,
            relief=tk.FLAT,
        )
        content.pack(fill=tk.BOTH, expand=True, padx=20)

        timeline_card = tk.Frame(content, bg=theme.C["surface"])
        timeline_wrap = tk.Frame(timeline_card, bg=theme.C["surface"])
        timeline_wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        timeline_scroll = ttk.Scrollbar(timeline_wrap)
        timeline_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._timeline = tk.Text(
            timeline_wrap,
            wrap=tk.WORD,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text"],
            relief=tk.FLAT,
            padx=6,
            pady=4,
            yscrollcommand=timeline_scroll.set,
            state=tk.DISABLED,
        )
        self._timeline.pack(fill=tk.BOTH, expand=True)
        timeline_scroll.config(command=self._timeline.yview)
        self._bind_local_wheel(self._timeline, self._timeline)
        self._configure_tags()
        content.add(timeline_card, minsize=250, stretch="always")

        lower = tk.Frame(content, bg=theme.C["surface"])
        self._permissions = tk.Frame(lower, bg="#FFF7ED")
        self._permissions.pack(fill=tk.X, padx=10, pady=(10, 0))

        tk.Label(
            lower,
            text="Уточнение для агента",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_label"],
        ).pack(anchor=tk.W, padx=10, pady=(10, 4))
        input_wrap = tk.Frame(lower, bg=theme.C["border"])
        input_wrap.pack(fill=tk.BOTH, expand=True, padx=10)
        self._input = tk.Text(
            input_wrap,
            height=4,
            wrap=tk.WORD,
            font=theme.F["body"],
            bg=theme.C["input_bg"],
            fg=theme.C["text"],
            insertbackground=theme.C["text"],
            relief=tk.FLAT,
            padx=8,
            pady=7,
        )
        self._input.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._input.bind("<Control-Return>", lambda _event: self._send())
        self._bind_local_wheel(self._input, self._input)

        buttons = tk.Frame(lower, bg=theme.C["surface"])
        buttons.pack(fill=tk.X, padx=10, pady=10)
        self._send_btn = ttk.Button(
            buttons,
            text="Отправить уточнение",
            style="Secondary.TButton",
            command=self._send,
        )
        self._send_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._finalize_btn = ttk.Button(
            buttons,
            text="Сформировать preview",
            style="Primary.TButton",
            command=self._on_finalize,
        )
        self._finalize_btn.pack(side=tk.LEFT)
        self._stop_btn = ttk.Button(
            buttons,
            text="Остановить",
            style="Secondary.TButton",
            command=self._on_stop,
        )
        self._stop_btn.pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            buttons,
            text="Отмена",
            style="Ghost.TButton",
            command=self.cancel,
        ).pack(side=tk.RIGHT)
        content.add(lower, minsize=190, stretch="never")

        # Колесо над рамками/заголовком окна прокручивает его timeline. Оно не
        # должно доходить до глобального canvas основной формы.
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._dlg.bind(sequence, self._scroll_dialog, add="+")

        self.append_event(
            ConversationEvent(
                "system",
                (
                    "Быстрое заполнение · без MCP"
                    if self._mode == "fill_only"
                    else "Исследование · read-only MCP"
                ),
                (
                    "Copilot уже передал значения полей. Агент сразу формирует "
                    "preview; поиск и инструменты технически отключены."
                    if self._mode == "fill_only"
                    else "Файлы и shell запрещены. Проверенные read-only JSON "
                    "Repository MCP-вызовы разрешены; изменения запрещены."
                ),
            )
        )
        self.set_busy(True)

    def _bind_local_wheel(self, widget: tk.Widget, target: tk.Text) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(
                sequence,
                lambda event, scroll_target=target: self._scroll_widget(
                    scroll_target,
                    event,
                ),
                add="+",
            )

    def _scroll_dialog(self, event: tk.Event) -> str:
        return self._scroll_widget(self._timeline, event)

    @staticmethod
    def _scroll_widget(widget: tk.Text, event: tk.Event) -> str:
        number = getattr(event, "num", None)
        if number == 4:
            units = -1
        elif number == 5:
            units = 1
        else:
            delta = getattr(event, "delta", 0)
            units = int(-1 * (delta / 120)) if delta else 0
            if units == 0 and delta:
                units = -1 if delta > 0 else 1
        if units:
            widget.yview_scroll(units, "units")
        return "break"

    def _configure_tags(self) -> None:
        self._timeline.tag_configure(
            "system_title", foreground=theme.C["primary"], font=theme.F["h3"]
        )
        self._timeline.tag_configure(
            "assistant_title", foreground="#7C3AED", font=theme.F["h3"]
        )
        self._timeline.tag_configure(
            "user_title", foreground=theme.C["success"], font=theme.F["h3"]
        )
        self._timeline.tag_configure(
            "tool_title", foreground="#0369A1", font=theme.F["h3"]
        )
        self._timeline.tag_configure(
            "warning_title", foreground=theme.C["warning"], font=theme.F["h3"]
        )
        self._timeline.tag_configure(
            "error_title", foreground=theme.C["error"], font=theme.F["h3"]
        )
        self._timeline.tag_configure(
            "body", foreground=theme.C["text"], spacing3=10
        )
        self._timeline.tag_configure(
            "detail", foreground=theme.C["text_muted"], spacing3=10
        )
        self._configure_markdown_tags()

    def _configure_markdown_tags(self) -> None:
        self._timeline.tag_configure(
            "md_bold", font=("Segoe UI", 10, "bold")
        )
        self._timeline.tag_configure(
            "md_italic", font=("Segoe UI", 10, "italic")
        )
        self._timeline.tag_configure(
            "md_code", font=("Consolas", 9), foreground="#7C3AED",
            background=theme.C["surface_alt"],
        )
        self._timeline.tag_configure(
            "md_code_block", font=("Consolas", 9),
            foreground=theme.C["text"], background=theme.C["surface_alt"],
            lmargin1=18, lmargin2=18, rmargin=18, spacing1=2, spacing3=2,
        )
        self._timeline.tag_configure(
            "md_heading_1", font=("Segoe UI", 15, "bold")
        )
        self._timeline.tag_configure(
            "md_heading_2", font=("Segoe UI", 13, "bold")
        )
        self._timeline.tag_configure(
            "md_heading_3", font=("Segoe UI", 11, "bold")
        )
        self._timeline.tag_configure(
            "md_link", foreground=theme.C["primary"], underline=True
        )
        self._timeline.tag_configure(
            "md_quote", foreground=theme.C["text_muted"],
            font=("Segoe UI", 10, "italic"),
        )
        self._timeline.tag_configure(
            "md_quote_marker", foreground=theme.C["primary"],
            font=("Segoe UI", 10, "bold"),
        )
        self._timeline.tag_configure(
            "md_list_marker", foreground=theme.C["primary"],
            font=("Segoe UI", 10, "bold"),
        )
        self._timeline.tag_configure("md_rule", foreground=theme.C["border"])

    def set_session(self, session_id: Optional[str]) -> None:
        if self.exists:
            self._session_var.set(
                f"session: {session_id}" if session_id else "session: —"
            )

    def set_status(self, message: str, *, error: bool = False) -> None:
        if not self.exists:
            return
        self._status_var.set(message)
        self._status_label.config(
            fg=theme.C["error"] if error else theme.C["warning"]
        )

    def set_busy(self, busy: bool) -> None:
        if not self.exists:
            return
        state = tk.DISABLED if busy else tk.NORMAL
        self._send_btn.config(state=state)
        self._finalize_btn.config(state=state)
        self._input.config(state=state)
        self._stop_btn.config(state=tk.NORMAL if busy else tk.DISABLED)
        if busy:
            self._spinner.pack(side=tk.LEFT, padx=(0, 8), before=self._status_label)
            self._start_spinner()
        else:
            self._stop_spinner()
            self._spinner.pack_forget()
            self._status_label.config(fg=theme.C["success"])

    def _start_spinner(self) -> None:
        if self._spinner_after_id is None and self.exists:
            self._animate_spinner()

    def _animate_spinner(self) -> None:
        self._spinner_after_id = None
        if not self.exists or str(self._stop_btn.cget("state")) == tk.DISABLED:
            return
        self._spinner.delete("all")
        self._spinner.create_arc(
            3,
            3,
            17,
            17,
            start=self._spinner_angle,
            extent=255,
            style=tk.ARC,
            outline=theme.C["primary"],
            width=3,
        )
        self._spinner_angle = (self._spinner_angle + 24) % 360
        self._spinner_after_id = self._dlg.after(55, self._animate_spinner)

    def _stop_spinner(self) -> None:
        if self._spinner_after_id is not None:
            try:
                self._dlg.after_cancel(self._spinner_after_id)
            except tk.TclError:
                pass
            self._spinner_after_id = None
        try:
            self._spinner.delete("all")
        except tk.TclError:
            pass

    def append_message(
        self,
        role: str,
        text: str,
        *,
        opencode_seconds: Optional[float] = None,
        generation_seconds: Optional[float] = None,
    ) -> None:
        clean = text.strip() or "Ответ не содержит текстовой части."
        titles = {
            "assistant": ("OpenCode", "assistant_title"),
            "user": ("Вы", "user_title"),
            "system": ("Система", "system_title"),
        }
        title, tag = titles.get(role, (role, "system_title"))
        thinking = self._thinking_level
        if self._thinking_auto and thinking != "—":
            thinking += " · авто"
        title += f" · thinking: {thinking}"
        if opencode_seconds is not None and opencode_seconds >= 0:
            title += f" · OpenCode: {opencode_seconds:.1f} с"
        if generation_seconds is not None and generation_seconds >= 0:
            title += f" · генерация: {generation_seconds:.1f} с"
        self._append(title, clean, tag, "body", markdown=role == "assistant")

    def append_event(self, event: ConversationEvent) -> None:
        if event.kind == "status":
            detail = f" · {event.detail}" if event.detail else ""
            self.set_status(event.title + detail)
            return
        tag = {
            "tool": "tool_title",
            "permission": "warning_title",
            "permission_resolved": "system_title",
            "warning": "warning_title",
            "error": "error_title",
            "system": "system_title",
        }.get(event.kind, "system_title")
        self._append(event.title, event.detail, tag, "detail")
        if event.kind == "permission" and event.permission_id:
            self._show_permission(event)
        elif event.kind == "permission_resolved" and event.permission_id:
            row = self._permission_rows.pop(event.permission_id, None)
            self._answered_permissions.add(event.permission_id)
            if row is not None:
                row.destroy()

    def _append(
        self,
        title: str,
        body: str,
        title_tag: str,
        body_tag: str,
        *,
        markdown: bool = False,
    ) -> None:
        if not self.exists:
            return
        self._timeline.config(state=tk.NORMAL)
        self._timeline.insert(tk.END, title + "\n", title_tag)
        if body:
            if markdown:
                insert_markdown(self._timeline, body, body_tag)
                self._timeline.insert(tk.END, "\n\n", body_tag)
            else:
                self._timeline.insert(tk.END, body + "\n\n", body_tag)
        else:
            self._timeline.insert(tk.END, "\n", body_tag)
        self._timeline.see(tk.END)
        self._timeline.config(state=tk.DISABLED)

    def _show_permission(self, event: ConversationEvent) -> None:
        if (
            event.permission_id in self._permission_rows
            or event.permission_id in self._answered_permissions
        ):
            return
        row = tk.Frame(self._permissions, bg="#FFF7ED")
        row.pack(fill=tk.X, padx=8, pady=6)
        text = event.permission_name
        if event.detail:
            text += f" · {event.detail[:300]}"
        tk.Label(
            row,
            text="MCP запрашивает: " + text,
            wraplength=650,
            justify=tk.LEFT,
            font=theme.F["small"],
            bg="#FFF7ED",
            fg=theme.C["warning"],
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            row,
            text="Разрешить один раз",
            style="Secondary.TButton",
            command=lambda: self._answer_permission(event.permission_id, True),
        ).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(
            row,
            text="Отклонить",
            style="Ghost.TButton",
            command=lambda: self._answer_permission(event.permission_id, False),
        ).pack(side=tk.RIGHT)
        self._permission_rows[event.permission_id] = row

    def _answer_permission(self, permission_id: str, allow: bool) -> None:
        row = self._permission_rows.get(permission_id)
        if row is not None:
            for child in row.winfo_children():
                if isinstance(child, ttk.Button):
                    child.config(state=tk.DISABLED)
        self.append_event(ConversationEvent(
            "system",
            "Разрешение MCP",
            "Отправляю решение серверу…",
        ))
        self._on_permission(permission_id, allow)

    def permission_answered(
        self,
        permission_id: str,
        allow: bool,
        error: str = "",
    ) -> None:
        row = self._permission_rows.get(permission_id)
        if error:
            if row is not None:
                for child in row.winfo_children():
                    if isinstance(child, ttk.Button):
                        child.config(state=tk.NORMAL)
            self.append_event(ConversationEvent(
                "error",
                "Не удалось ответить на permission request",
                error,
            ))
            return
        if permission_id in self._answered_permissions and row is None:
            return
        row = self._permission_rows.pop(permission_id, None)
        self._answered_permissions.add(permission_id)
        if row is not None:
            row.destroy()
        self.append_event(ConversationEvent(
            "system",
            "Разрешение MCP",
            "Разрешено один раз." if allow else "Вызов отклонён.",
        ))

    def _send(self) -> None:
        if not self.exists:
            return
        text = self._input.get("1.0", "end-1c").strip()
        if not text:
            return
        self._input.delete("1.0", tk.END)
        self.append_message("user", text)
        self._on_send(text)

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._on_cancel()

    def close(self) -> None:
        if not self.exists:
            return
        self._stop_spinner()
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()

    def _center(self) -> None:
        self._dlg.update_idletasks()
        root = self._parent.winfo_toplevel()
        width = min(980, max(780, root.winfo_screenwidth() - 80))
        height = min(700, max(560, root.winfo_screenheight() - 100))
        x = max(0, root.winfo_rootx() + (root.winfo_width() - width) // 2)
        y = max(0, root.winfo_rooty() + (root.winfo_height() - height) // 2)
        self._dlg.geometry(f"{width}x{height}+{x}+{y}")
