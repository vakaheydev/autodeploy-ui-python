"""Компактный AI-чат главного экрана для выбора формы по заявке."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Optional

import ui.theme as theme
from config.environments import (
    OPENCODE_MAX_CONTEXT_CHARS_KEY,
    OPENCODE_MODEL_ID_KEY,
    OPENCODE_PROVIDER_ID_KEY,
)
from forms.registry import FormRegistry
from opencode_integration.client import OpenCodeCancelled
from opencode_integration.router import (
    FormRouter,
    RoutingOutcome,
    extract_ticket_id,
)
from ui.dialogs import ask_ticket_id


_log = logging.getLogger("opencode.home_chat")


class AIHomeChat(tk.Frame):
    """Ticket → route → existing FormScreen AI workflow."""

    def __init__(self, master: tk.Widget, *, app) -> None:
        super().__init__(master, bg=theme.C["border"])
        self.app = app
        self._queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._cancel_event: Optional[threading.Event] = None
        self._router: Optional[FormRouter] = None
        self._outcome: Optional[RoutingOutcome] = None
        self._poll_id: Optional[str] = None
        self._busy = False
        self._destroying = False
        self._connected_address = ""
        self._build()

    def _build(self) -> None:
        surface = tk.Frame(self, bg=theme.C["surface"])
        surface.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        heading = tk.Frame(surface, bg=theme.C["surface"])
        heading.pack(fill=tk.X, padx=16, pady=(14, 3))
        tk.Label(
            heading,
            text="✦  AI-помощник по заявкам",
            font=theme.F["h2"],
            bg=theme.C["surface"],
            fg=theme.C["text"],
        ).pack(side=tk.LEFT)
        self._connection_label = tk.Label(
            heading,
            text="● OpenCode",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["success"],
        )
        self._connection_label.pack(side=tk.RIGHT)

        tk.Label(
            surface,
            text=(
                "Отправьте номер заявки. Помощник выберет форму и запустит "
                "существующий сценарий AI-заполнения."
            ),
            wraplength=590,
            justify=tk.LEFT,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

        self._transcript = tk.Text(
            surface,
            height=7,
            wrap=tk.WORD,
            font=theme.F["small"],
            bg=theme.C["surface_alt"],
            fg=theme.C["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            state=tk.DISABLED,
            cursor="arrow",
        )
        self._transcript.pack(fill=tk.X, padx=16)
        self._transcript.tag_configure(
            "assistant", foreground=theme.C["text"], spacing1=3, spacing3=5
        )
        self._transcript.tag_configure(
            "user", foreground=theme.C["primary"], spacing1=3, spacing3=5
        )
        self._transcript.tag_configure(
            "error", foreground=theme.C["error"], spacing1=3, spacing3=5
        )
        self._append("assistant", "Готов определить форму. Пришлите номер заявки.")

        self._candidate_frame = tk.Frame(surface, bg=theme.C["surface"])
        self._candidate_frame.pack(fill=tk.X, padx=16, pady=(6, 0))

        self._status_var = tk.StringVar(value="")
        self._status_label = tk.Label(
            surface,
            textvariable=self._status_var,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            anchor="w",
        )
        self._status_label.pack(fill=tk.X, padx=16, pady=(6, 2))
        self._progress = ttk.Progressbar(surface, mode="indeterminate")

        self._input_row = tk.Frame(surface, bg=theme.C["surface"])
        self._input_row.pack(fill=tk.X, padx=16, pady=(5, 14))
        self._input = ttk.Entry(self._input_row, font=theme.F["body"])
        self._input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        self._input.bind("<Return>", lambda _event: self._send())
        self._pick_button = ttk.Button(
            self._input_row,
            text="Выбрать заявку",
            style="Secondary.TButton",
            command=self._pick_ticket,
        )
        self._pick_button.pack(side=tk.LEFT, padx=(8, 0))
        self._send_button = ttk.Button(
            self._input_row,
            text="Отправить",
            style="Primary.TButton",
            command=self._send,
        )
        self._send_button.pack(side=tk.LEFT, padx=(8, 0))
        self._cancel_button = ttk.Button(
            self._input_row,
            text="Остановить",
            style="Secondary.TButton",
            command=self._cancel_request,
        )

    def connected(self, address: str) -> None:
        self._connected_address = address
        self._connection_label.config(text=f"● {address or 'OpenCode'}")

    def disconnected(self) -> None:
        self._connected_address = ""
        if self._busy:
            self._cancel_request()

    def _pick_ticket(self) -> None:
        ticket_id = ask_ticket_id(self)
        if ticket_id:
            self._start(ticket_id)

    def _send(self) -> None:
        if self._busy:
            return
        try:
            ticket_id = extract_ticket_id(self._input.get())
        except Exception as exc:
            self._append("error", str(exc))
            self._status("Укажите один номер заявки.", error=True)
            return
        self._input.delete(0, tk.END)
        self._start(ticket_id)

    def _start(self, ticket_id: str) -> None:
        if self._busy:
            return
        client = self.app.opencode_manager.client
        if client is None:
            self._append("error", "Соединение с OpenCode потеряно.")
            self._status("Подключитесь к OpenCode Server.", error=True)
            return

        self._clear_candidates()
        self._outcome = None
        self._append("user", ticket_id)
        settings = self.app.env_manager.load()
        provider_id = settings.get(OPENCODE_PROVIDER_ID_KEY, "").strip()
        model_id = settings.get(OPENCODE_MODEL_ID_KEY, "").strip()
        try:
            max_context_chars = int(
                settings.get(OPENCODE_MAX_CONTEXT_CHARS_KEY, "120000")
            )
        except (TypeError, ValueError):
            max_context_chars = 120_000
        environment = self.app.current_environment.get()
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._set_busy(True)

        def progress(message: str) -> None:
            self._queue.put(("progress", message))

        def session_changed(session_id: Optional[str]) -> None:
            self._queue.put(("session", session_id))

        def worker() -> None:
            router: Optional[FormRouter] = None
            try:
                router = FormRouter(
                    client,
                    self.app.itsm_service,
                    self.app.tfs_service,
                    forms=FormRegistry().all_forms(),
                    max_context_chars=max_context_chars,
                )
                self._router = router
                outcome = router.route(
                    ticket_id=ticket_id,
                    environment=environment,
                    provider_id=provider_id,
                    model_id=model_id,
                    cancel_event=cancel_event,
                    on_progress=progress,
                    on_session=session_changed,
                )
            except Exception as exc:
                self._queue.put(("error", exc))
            else:
                self._queue.put(("result", outcome))
            finally:
                if router is not None:
                    router.close(on_session=session_changed)

        threading.Thread(
            target=worker,
            name="opencode-form-router",
            daemon=True,
        ).start()
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._poll_id is None and not self._destroying:
            self._poll_id = self.after(80, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        try:
            while True:
                event, payload = self._queue.get_nowait()
                if event == "progress":
                    self._status(str(payload))
                elif event == "session" and payload:
                    _log.info("home routing session=%s", payload)
                elif event == "result":
                    self._finish(payload)
                elif event == "error":
                    self._fail(payload)
        except queue.Empty:
            pass
        if self._busy and not self._destroying:
            self._schedule_poll()

    def _finish(self, outcome: RoutingOutcome) -> None:
        self._router = None
        self._cancel_event = None
        self._outcome = outcome
        if not self._connected_address:
            self._fail(OpenCodeCancelled("Соединение с OpenCode потеряно"))
            return
        decision = outcome.decision
        if decision.selected_form_id:
            candidate = next(
                item for item in decision.candidates
                if item.form_id == decision.selected_form_id
            )
            form = FormRegistry().get(candidate.form_id)
            self._append(
                "assistant",
                f"Выбрана форма «{form.title}» — {candidate.score}/100. "
                f"{decision.reason}",
            )
            self._status("Открываю форму и запускаю AI-заполнение…")
            self._set_busy(False)
            self._input.config(state=tk.DISABLED)
            self._pick_button.config(state=tk.DISABLED)
            self._send_button.config(state=tk.DISABLED)
            self.after(180, lambda: self._open_form(candidate.form_id))
            return

        self._append("assistant", f"{decision.question}\n{decision.reason}")
        self._render_candidates(outcome)
        self._status("Нужен ваш выбор. Основная форма пока не изменена.")
        self._set_busy(False)

    def _render_candidates(self, outcome: RoutingOutcome) -> None:
        self._clear_candidates()
        for candidate in outcome.decision.candidates:
            form = FormRegistry().get(candidate.form_id)
            row = tk.Frame(self._candidate_frame, bg=theme.C["surface_alt"])
            row.pack(fill=tk.X, pady=2)
            label = tk.Label(
                row,
                text=f"{form.title}  ·  {candidate.score}/100\n{candidate.reason}",
                wraplength=440,
                justify=tk.LEFT,
                anchor="w",
                font=theme.F["small"],
                bg=theme.C["surface_alt"],
                fg=theme.C["text"],
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=7)
            ttk.Button(
                row,
                text="Использовать",
                style="Secondary.TButton",
                command=lambda form_id=candidate.form_id: self._open_form(form_id),
            ).pack(side=tk.RIGHT, padx=8, pady=6)

    def _open_form(self, form_id: str) -> None:
        outcome = self._outcome
        if outcome is None or self._destroying:
            return
        context = outcome.context
        self._outcome = None
        _log.info("home routing accepted ticket=%s form=%s", context.ticket_id, form_id)
        self.app.open_ai_routed_form(form_id, context)

    def _fail(self, error: Exception) -> None:
        self._router = None
        self._cancel_event = None
        self._outcome = None
        self._set_busy(False)
        if isinstance(error, OpenCodeCancelled):
            self._append("assistant", "Операция остановлена. Никакая форма не изменена.")
            self._status("Операция отменена.")
        else:
            self._append("error", f"Не удалось выбрать форму: {error}")
            self._status("Ошибка выбора формы. Можно повторить запрос.", error=True)

    def _cancel_request(self) -> None:
        if not self._busy:
            return
        if self._cancel_event is not None:
            self._cancel_event.set()
        router = self._router
        self._status("Останавливаю запрос…")
        if router is not None:
            threading.Thread(
                target=router.cancel,
                name="opencode-form-router-abort",
                daemon=True,
            ).start()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self._input.config(state=state)
        self._pick_button.config(state=state)
        self._send_button.config(state=state)
        if busy:
            self._cancel_button.pack(side=tk.LEFT, padx=(8, 0))
            self._progress.pack(
                fill=tk.X,
                padx=16,
                pady=(0, 2),
                before=self._input_row,
            )
            self._progress.start(10)
        else:
            self._cancel_button.pack_forget()
            self._progress.stop()
            self._progress.pack_forget()

    def _status(self, message: str, *, error: bool = False) -> None:
        self._status_var.set(message)
        self._status_label.config(
            fg=theme.C["error"] if error else theme.C["text_muted"]
        )

    def _append(self, role: str, message: str) -> None:
        prefixes = {"assistant": "AI", "user": "Вы", "error": "Ошибка"}
        self._transcript.config(state=tk.NORMAL)
        if self._transcript.index("end-1c") != "1.0":
            self._transcript.insert(tk.END, "\n")
        self._transcript.insert(
            tk.END,
            f"{prefixes.get(role, role)}: {str(message).strip()}\n",
            role,
        )
        self._transcript.config(state=tk.DISABLED)
        self._transcript.see(tk.END)

    def _clear_candidates(self) -> None:
        for child in self._candidate_frame.winfo_children():
            child.destroy()

    def detach_for_shutdown(self) -> Optional[FormRouter]:
        self._destroying = True
        if self._cancel_event is not None:
            self._cancel_event.set()
        router = self._router
        self._router = None
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        return router

    def shutdown(self) -> None:
        router = self.detach_for_shutdown()
        if router is not None:
            threading.Thread(
                target=router.cancel,
                name="opencode-home-chat-cleanup",
                daemon=True,
            ).start()
