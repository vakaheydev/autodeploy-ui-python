"""Главный AI-чат: единая точка входа в формы и Gravitee repository."""
from __future__ import annotations

import json
import logging
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import ttk
from typing import Any, Optional

import ui.theme as theme
from config.environments import (
    OPENCODE_ALLOWED_MCP_KEY,
    OPENCODE_MAX_CONTEXT_CHARS_KEY,
    OPENCODE_REPOSITORY_GIT_PULL_KEY,
    OPENCODE_REPOSITORY_MCP_KEY,
)
from config.mcp_profiles import setting_enabled
from forms.registry import FormRegistry
from opencode_integration.agent import ConversationEvent
from opencode_integration.client import OpenCodeCancelled, OpenCodeModel
from opencode_integration.copilot import CopilotOutcome, UnifiedCopilot
from ui.dialogs import ask_ticket_id, show_confirm, show_error


_log = logging.getLogger("opencode.home_chat")
_DEFAULT_MODEL_LABEL = "По умолчанию из opencode.json"
_DEFAULT_VARIANT_LABEL = "По умолчанию"


class AIHomeChat(tk.Frame):
    """Natural language → validated copilot outcome → explicit user action."""

    def __init__(self, master: tk.Widget, *, app) -> None:
        super().__init__(master, bg=theme.C["border"])
        self.app = app
        self._queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._cancel_event: Optional[threading.Event] = None
        self._copilot: Optional[UnifiedCopilot] = getattr(
            app, "home_copilot", None
        )
        self._outcome: Optional[CopilotOutcome] = None
        self._running_model: tuple[str, str, str] = ("", "", "")
        self._outcome_model: tuple[str, str, str] = ("", "", "")
        self._poll_id: Optional[str] = None
        self._busy = False
        self._destroying = False
        self._connected_address = ""
        self._session_id = ""
        self._last_status_key = ""
        self._permission_rows: dict[str, tk.Frame] = {}
        self._pending_checked = False
        self._models_loading = False
        self._models_address = ""
        self._model_by_label: dict[str, OpenCodeModel] = {}
        self._spinner_after_id: Optional[str] = None
        self._spinner_angle = 0
        self._build()
        if self._copilot is not None and self._copilot.session_id:
            self._set_session(self._copilot.session_id)

    def _build(self) -> None:
        surface = tk.Frame(self, bg=theme.C["surface"])
        surface.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        hero_bg = theme.C["chat_status"]
        hero = tk.Frame(surface, bg=hero_bg)
        hero.pack(fill=tk.X)
        heading = tk.Frame(hero, bg=hero_bg)
        heading.pack(fill=tk.X, padx=18, pady=(15, 5))
        tk.Label(
            heading, text="✦", font=("Segoe UI", 17, "bold"),
            bg=hero_bg, fg=theme.C["primary"],
        ).pack(side=tk.LEFT)
        title = tk.Frame(heading, bg=hero_bg)
        title.pack(side=tk.LEFT, padx=(9, 0))
        tk.Label(
            title, text="Gravitee Copilot", font=theme.F["h2"],
            bg=hero_bg, fg=theme.C["text"],
        ).pack(anchor=tk.W)
        tk.Label(
            title, text="Единая точка входа в формы, заявки и Gravitee Repository",
            font=theme.F["small"], bg=hero_bg, fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, pady=(1, 0))
        self._connection_label = tk.Label(
            heading, text="●  OpenCode", font=theme.F["small"],
            bg=theme.C["success_soft"], fg=theme.C["success"], padx=9, pady=4,
        )
        self._connection_label.pack(side=tk.RIGHT)
        self._session_button = ttk.Button(
            heading,
            text="Открыть сессию ↗",
            style="Chip.TButton",
            command=self._open_session_in_browser,
        )
        tk.Label(
            hero,
            text=(
                "Опишите результат, который нужен. Copilot сам выберет форму или план, "
                "а любые изменения покажет до применения."
            ),
            wraplength=820, justify=tk.LEFT, font=theme.F["small"],
            bg=hero_bg, fg=theme.C["text_label"],
        ).pack(fill=tk.X, padx=18, pady=(2, 8))

        model_row = tk.Frame(hero, bg=hero_bg)
        model_row.pack(fill=tk.X, padx=18, pady=(0, 14))
        tk.Label(
            model_row, text="Модель", font=theme.F["small"],
            bg=hero_bg, fg=theme.C["text_label"],
        ).pack(side=tk.LEFT, padx=(0, 6))
        self._model_var = tk.StringVar(value="Загрузка из opencode.json…")
        self._model_combo = ttk.Combobox(
            model_row,
            textvariable=self._model_var,
            state="disabled",
            width=43,
        )
        self._model_combo.pack(side=tk.LEFT, padx=(0, 12))
        self._model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)
        tk.Label(
            model_row, text="Thinking", font=theme.F["small"],
            bg=hero_bg, fg=theme.C["text_label"],
        ).pack(side=tk.LEFT, padx=(0, 6))
        self._variant_var = tk.StringVar(value=_DEFAULT_VARIANT_LABEL)
        self._variant_combo = ttk.Combobox(
            model_row,
            textvariable=self._variant_var,
            values=(_DEFAULT_VARIANT_LABEL,),
            state="disabled",
            width=15,
        )
        self._variant_combo.pack(side=tk.LEFT)
        self._reload_models_button = ttk.Button(
            model_row,
            text="↻",
            width=3,
            style="Chip.TButton",
            command=self._reload_models,
        )
        self._reload_models_button.pack(side=tk.LEFT, padx=(6, 0))

        quick = tk.Frame(surface, bg=theme.C["surface"])
        quick.pack(fill=tk.X, padx=16, pady=(12, 9))
        for label, prompt in (
            ("⌕  Найти API", "Найди API по имени, пути или backend URL: "),
            ("⌕  Приложение", "Найди приложение по имени, ID или client_id: "),
            ("≋  Похожие", "Найди похожие API или приложения для шаблона: "),
            ("✓  План заявки", "Построй полный многошаговый план исполнения заявки "),
        ):
            ttk.Button(
                quick, text=label, style="Chip.TButton",
                command=lambda value=prompt: self._set_input(value),
            ).pack(side=tk.LEFT, padx=(0, 6))

        transcript_border = tk.Frame(surface, bg=theme.C["border"])
        transcript_border.pack(fill=tk.BOTH, expand=True, padx=16)
        transcript_body = tk.Frame(transcript_border, bg=theme.C["chat_bg"])
        transcript_body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._transcript = tk.Text(
            transcript_body, height=14, wrap=tk.WORD, font=theme.F["body"],
            bg=theme.C["chat_bg"], fg=theme.C["text"], relief="flat", bd=0,
            padx=8, pady=8, state=tk.DISABLED, cursor="arrow",
        )
        transcript_scroll = ttk.Scrollbar(
            transcript_body, orient=tk.VERTICAL, command=self._transcript.yview
        )
        self._transcript.configure(yscrollcommand=transcript_scroll.set)
        # HomeScreen оставляет колесо этому вложенному скроллу. Над остальными
        # частями чата колесо прокручивает всю главную страницу.
        self._transcript._owns_mousewheel = True  # type: ignore[attr-defined]
        transcript_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._transcript.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._configure_transcript_tags()
        for role, message in self.app.copilot_history:
            self._append(role, message, remember=False)
        if not self.app.copilot_history:
            self._append(
                "assistant",
                "Опишите задачу обычным текстом или пришлите номер заявки. "
                "Репозиторные факты я ищу только через проверенные read-only MCP-вызовы.",
            )

        self._permission_frame = tk.Frame(surface, bg=theme.C["surface"])
        self._permission_frame.pack(fill=tk.X, padx=16, pady=(5, 0))
        self._plan_frame = tk.Frame(surface, bg=theme.C["surface"])
        self._plan_frame.pack(fill=tk.X, padx=16, pady=(5, 0))
        self._action_frame = tk.Frame(surface, bg=theme.C["surface"])
        self._action_frame.pack(fill=tk.X, padx=16, pady=(5, 0))
        self._render_active_plan()

        self._status_panel = tk.Frame(surface, bg=theme.C["chat_status"])
        self._status_panel.pack(fill=tk.X, padx=16, pady=(9, 0))
        self._status_dot = tk.Label(
            self._status_panel, text="●", font=theme.F["small"],
            bg=theme.C["chat_status"], fg=theme.C["success"],
        )
        self._status_dot.pack(side=tk.LEFT, padx=(10, 6), pady=7)
        self._spinner = tk.Canvas(
            self._status_panel,
            width=20,
            height=20,
            bg=theme.C["chat_status"],
            highlightthickness=0,
            bd=0,
        )
        self._status_var = tk.StringVar(value="Готов к работе")
        self._status_label = tk.Label(
            self._status_panel, textvariable=self._status_var, font=theme.F["small"],
            bg=theme.C["chat_status"], fg=theme.C["text_label"], anchor="w",
        )
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=7)
        self._cancel_button = ttk.Button(
            self._status_panel, text="Остановить", style="DangerGhost.TButton",
            command=self._cancel_request,
        )
        self._input_row = tk.Frame(surface, bg=theme.C["border_focus"])
        self._input_row.pack(fill=tk.X, padx=16, pady=(9, 4))
        composer = tk.Frame(self._input_row, bg=theme.C["input_bg"])
        composer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._input = tk.Text(
            composer, height=3, wrap=tk.WORD, font=theme.F["body"],
            bg=theme.C["input_bg"], fg=theme.C["text"], relief="flat", bd=0,
            padx=10, pady=8, insertbackground=theme.C["text"],
        )
        self._input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._input.bind("<Return>", self._on_enter)
        self._pick_button = ttk.Button(
            composer, text="＋ Заявка", style="Chip.TButton",
            command=self._pick_ticket,
        )
        self._pick_button.pack(side=tk.LEFT, padx=(5, 6), pady=7)
        self._send_button = ttk.Button(
            composer, text="Отправить  ↑", style="Primary.TButton", command=self._send,
        )
        self._send_button.pack(side=tk.LEFT, padx=(0, 7), pady=7)
        tk.Label(
            surface,
            text="Enter — отправить   ·   Shift+Enter — новая строка",
            font=("Segoe UI", 9), bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.E, padx=17, pady=(0, 11))

    def _configure_transcript_tags(self) -> None:
        common = {"font": theme.F["small"], "foreground": theme.C["text_muted"]}
        self._transcript.tag_configure(
            "assistant_meta", **common, lmargin1=16, lmargin2=16,
            rmargin=130, spacing1=10, spacing3=3,
        )
        self._transcript.tag_configure(
            "assistant", font=theme.F["body"], foreground=theme.C["text"],
            background=theme.C["chat_ai"], lmargin1=16, lmargin2=16,
            rmargin=130, spacing3=10,
        )
        self._transcript.tag_configure(
            "user_meta", font=("Segoe UI", 9, "bold"), foreground=theme.C["primary"],
            justify=tk.RIGHT, lmargin1=130, lmargin2=130, rmargin=16,
            spacing1=10, spacing3=3,
        )
        self._transcript.tag_configure(
            "user", font=theme.F["body"], foreground=theme.C["text"],
            background=theme.C["chat_user"], justify=tk.RIGHT,
            lmargin1=130, lmargin2=130, rmargin=16, spacing3=10,
        )
        self._transcript.tag_configure(
            "error_meta", font=("Segoe UI", 9, "bold"), foreground=theme.C["error"],
            lmargin1=16, lmargin2=16, rmargin=80, spacing1=10, spacing3=3,
        )
        self._transcript.tag_configure(
            "error", font=theme.F["body"], foreground="#991B1B",
            background=theme.C["chat_error"], lmargin1=16, lmargin2=16,
            rmargin=80, spacing3=10,
        )
        self._transcript.tag_configure(
            "activity", font=("Segoe UI", 9), foreground=theme.C["text_muted"],
            lmargin1=28, lmargin2=28, rmargin=28, spacing1=3, spacing3=4,
        )

    def connected(self, address: str) -> None:
        if self._copilot is not None and self._copilot.server_url != address:
            previous = self._copilot
            self._copilot = None
            if getattr(self.app, "home_copilot", None) is previous:
                self.app.home_copilot = None
            self._set_session("")
            threading.Thread(
                target=previous.close,
                name="opencode-previous-server-session-cleanup",
                daemon=True,
            ).start()
        self._connected_address = address
        short_address = (address or "OpenCode").removeprefix("http://")
        self._connection_label.config(
            text=f"●  {short_address}",
            bg=theme.C["success_soft"],
            fg=theme.C["success"],
        )
        if address != self._models_address:
            self._load_models_from_opencode(address)
        elif not self._models_loading:
            self._set_model_controls_enabled(True)
        if not self._pending_checked:
            self._pending_checked = True
            self.after(120, self._consume_pending_request)

    def disconnected(self) -> None:
        self._connected_address = ""
        self._connection_label.config(
            text="●  Нет соединения", bg=theme.C["chat_error"], fg=theme.C["error"]
        )
        self._set_model_controls_enabled(False)
        if self._busy:
            self._cancel_request()

    def _reload_models(self) -> None:
        if self._connected_address and not self._models_loading:
            self._load_models_from_opencode(self._connected_address, force=True)

    def _load_models_from_opencode(self, address: str, *, force: bool = False) -> None:
        if self._destroying or self._models_loading:
            return
        if not force and address == self._models_address and self._model_by_label:
            return
        client = self.app.opencode_manager.client
        if client is None:
            return
        self._models_loading = True
        self._models_address = address
        self._model_var.set("Загрузка из opencode.json…")
        self._set_model_controls_enabled(False)

        def worker() -> None:
            try:
                models = client.list_configured_models(timeout=10.0)
            except Exception as exc:
                self._queue.put(("models_error", (address, exc)))
            else:
                self._queue.put(("models", (address, models)))

        threading.Thread(
            target=worker,
            name="opencode-model-catalog",
            daemon=True,
        ).start()
        self._schedule_poll()

    @staticmethod
    def _model_label(model: OpenCodeModel) -> str:
        return (
            f"{model.model_name} · {model.provider_id}/{model.model_id}"
        )

    def _apply_models(self, address: str, models: list[OpenCodeModel]) -> None:
        self._models_loading = False
        if address != self._connected_address:
            return
        previous = self._model_by_label.get(self._model_var.get())
        self._models_address = address
        self._model_by_label = {
            self._model_label(model): model
            for model in models
        }
        labels = [_DEFAULT_MODEL_LABEL, *self._model_by_label]
        self._model_combo.configure(values=labels)

        selected = _DEFAULT_MODEL_LABEL
        preferred_variant = self._variant_var.get()
        if previous is not None:
            selected = next(
                (
                    label
                    for label, item in self._model_by_label.items()
                    if (item.provider_id, item.model_id)
                    == (previous.provider_id, previous.model_id)
                ),
                selected,
            )
        else:
            remembered = (
                self._copilot.model_selection
                if self._copilot is not None
                else ("", "", "")
            )
            configured = remembered[:2]
            if remembered[1]:
                preferred_variant = remembered[2] or _DEFAULT_VARIANT_LABEL
            selected = next(
                (
                    label
                    for label, item in self._model_by_label.items()
                    if (item.provider_id, item.model_id) == configured
                ),
                selected,
            )
        self._model_var.set(selected)
        self._sync_variant_choices()
        selected_model = self._model_by_label.get(selected)
        if (
            selected_model is not None
            and preferred_variant in selected_model.variants
        ):
            self._variant_var.set(preferred_variant)
        self._set_model_controls_enabled(True)
        if models and not self._busy:
            self._status(
                f"Загружено моделей из opencode.json: {len(models)}."
            )
        elif not models and not self._busy:
            self._status(
                "В opencode.json нет доступных моделей; используется выбор OpenCode.",
                error=True,
            )

    def _models_failed(self, address: str, error: Exception) -> None:
        self._models_loading = False
        if address != self._connected_address:
            return
        self._model_by_label.clear()
        self._model_combo.configure(values=(_DEFAULT_MODEL_LABEL,))
        self._model_var.set(_DEFAULT_MODEL_LABEL)
        self._sync_variant_choices()
        self._set_model_controls_enabled(True)
        _log.warning(
            "failed to load OpenCode model catalog error_type=%s",
            type(error).__name__,
        )
        if not self._busy:
            self._status(
                "Не удалось прочитать модели из opencode.json; используется default OpenCode.",
                error=True,
            )

    def _on_model_selected(self, _event: Optional[tk.Event] = None) -> None:
        self._sync_variant_choices()

    def _sync_variant_choices(self) -> None:
        model = self._model_by_label.get(self._model_var.get())
        variants = model.variants if model is not None else ()
        values = (_DEFAULT_VARIANT_LABEL, *variants)
        current = self._variant_var.get()
        self._variant_combo.configure(values=values)
        self._variant_var.set(current if current in values else _DEFAULT_VARIANT_LABEL)

    def _set_model_controls_enabled(self, enabled: bool) -> None:
        active = enabled and bool(self._connected_address) and not self._busy
        self._model_combo.configure(state="readonly" if active else "disabled")
        self._variant_combo.configure(state="readonly" if active else "disabled")
        self._reload_models_button.configure(
            state=tk.NORMAL if active and not self._models_loading else tk.DISABLED
        )

    def _selected_model(self) -> tuple[str, str, str]:
        model = self._model_by_label.get(self._model_var.get())
        if model is not None:
            variant = self._variant_var.get().strip()
            if variant == _DEFAULT_VARIANT_LABEL or variant not in model.variants:
                variant = ""
            return model.provider_id, model.model_id, variant
        if self._models_loading and self._copilot is not None:
            return self._copilot.model_selection
        return "", "", ""

    def _consume_pending_request(self) -> None:
        if self._destroying or not self._connected_address:
            self._pending_checked = False
            return
        pending = self.app.consume_copilot_request()
        if pending is not None:
            message, diagnostics, ticket_id = pending
            self._start(message, ticket_id=ticket_id, diagnostic_data=diagnostics)

    def _pick_ticket(self) -> None:
        ticket_id = ask_ticket_id(self)
        if ticket_id:
            self._start(
                f"Проанализируй заявку {ticket_id}: выбери одну форму или построй "
                "многошаговый план, если операций несколько.",
                ticket_id=ticket_id,
            )

    def _on_enter(self, event: tk.Event) -> Optional[str]:
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _send(self) -> None:
        if self._busy:
            return
        message = self._input.get("1.0", "end-1c").strip()
        if not message:
            self._status("Введите вопрос, задачу или номер заявки.", error=True)
            return
        self._input.delete("1.0", tk.END)
        self._start(message)

    def _start(
        self, message: str, *, ticket_id: Optional[str] = None,
        diagnostic_data: Any = None,
    ) -> None:
        if self._busy:
            return
        client = self.app.opencode_manager.client
        if client is None:
            self._append("error", "Соединение с OpenCode потеряно.")
            self._status("Подключитесь к OpenCode Server.", error=True)
            return
        self._clear_actions()
        self._clear_permissions()
        self._outcome = None
        self._outcome_model = ("", "", "")
        self._append("user", message)
        settings = self.app.env_manager.load()
        provider_id, model_id, variant = self._selected_model()
        self._running_model = (provider_id, model_id, variant)
        allowed_mcp = self._parse_mcp(settings.get(OPENCODE_ALLOWED_MCP_KEY, ""))
        repository_mcp = settings.get(OPENCODE_REPOSITORY_MCP_KEY, "").strip()
        allow_repository_git_pull = setting_enabled(
            settings.get(OPENCODE_REPOSITORY_GIT_PULL_KEY, "true")
        )
        try:
            max_context_chars = int(settings.get(OPENCODE_MAX_CONTEXT_CHARS_KEY, "120000"))
        except (TypeError, ValueError):
            max_context_chars = 120_000
        if self._copilot is None:
            self._copilot = UnifiedCopilot(
                client, self.app.itsm_service, self.app.tfs_service,
                forms=FormRegistry().all_forms(), allowed_mcp=allowed_mcp,
                repository_mcp=repository_mcp,
                allow_repository_git_pull=allow_repository_git_pull,
                max_context_chars=max_context_chars,
            )
            self.app.home_copilot = self._copilot
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._set_busy(True)
        self._status("Готовлю контекст и запускаю OpenCode…")

        def progress(value: str) -> None:
            self._queue.put(("progress", value))

        def conversation(event: ConversationEvent) -> None:
            self._queue.put(("conversation", event))

        def session_changed(session_id: Optional[str]) -> None:
            self._queue.put(("session", session_id))

        copilot = self._copilot

        def worker() -> None:
            try:
                outcome = copilot.ask(
                    message, environment=self.app.current_environment.get(),
                    ticket_id=ticket_id, diagnostic_data=diagnostic_data,
                    provider_id=provider_id, model_id=model_id,
                    variant=variant,
                    cancel_event=cancel_event, on_progress=progress,
                    on_event=conversation, on_session=session_changed,
                )
            except Exception as exc:
                self._queue.put(("error", exc))
            else:
                self._queue.put(("result", outcome))

        threading.Thread(target=worker, name="opencode-unified-copilot", daemon=True).start()
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
                elif event == "conversation":
                    self._handle_conversation_event(payload)
                elif event == "session":
                    self._set_session(str(payload) if payload else "")
                elif event == "models":
                    address, models = payload
                    self._apply_models(str(address), list(models))
                elif event == "models_error":
                    address, error = payload
                    self._models_failed(str(address), error)
                elif event == "permission_answered":
                    self._permission_answered(*payload)
                elif event == "result":
                    self._finish(payload)
                elif event == "error":
                    self._fail(payload)
        except queue.Empty:
            pass
        if (self._busy or self._models_loading) and not self._destroying:
            self._schedule_poll()

    def _handle_conversation_event(self, event: ConversationEvent) -> None:
        if event.kind == "permission":
            self._render_permission(event)
            return
        if event.kind == "status":
            key = f"{event.title}\0{event.detail}"
            if key != self._last_status_key:
                self._last_status_key = key
                detail = f" · {event.detail}" if event.detail else ""
                self._status(event.title + detail)
            return
        detail = f" — {event.detail}" if event.detail else ""
        role = "error" if event.kind == "error" else "activity"
        self._append(role, event.title + detail, remember=False)

    def _render_permission(self, event: ConversationEvent) -> None:
        permission_id = event.permission_id
        if not permission_id or permission_id in self._permission_rows:
            return
        row = tk.Frame(self._permission_frame, bg="#FEF3C7")
        row.pack(fill=tk.X, pady=2)
        self._permission_rows[permission_id] = row
        tk.Label(
            row,
            text=f"MCP просит разрешение на один вызов: {event.permission_name}\n{event.detail}",
            wraplength=540, justify=tk.LEFT, anchor="w", font=theme.F["small"],
            bg="#FEF3C7", fg=theme.C["text"],
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=6)
        ttk.Button(
            row, text="Разрешить один раз", style="Primary.TButton",
            command=lambda: self._answer_permission(permission_id, True),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            row, text="Отклонить", style="Secondary.TButton",
            command=lambda: self._answer_permission(permission_id, False),
        ).pack(side=tk.LEFT, padx=(0, 8))

    def _answer_permission(self, permission_id: str, allow: bool) -> None:
        copilot = self._copilot
        row = self._permission_rows.get(permission_id)
        if copilot is None:
            return
        if row is not None:
            for child in row.winfo_children():
                try:
                    child.config(state=tk.DISABLED)
                except tk.TclError:
                    pass

        def worker() -> None:
            try:
                copilot.approve_permission(permission_id, allow=allow)
            except Exception as exc:
                self._queue.put(("permission_answered", (permission_id, allow, exc)))
            else:
                self._queue.put(("permission_answered", (permission_id, allow, None)))

        threading.Thread(target=worker, name="opencode-copilot-permission", daemon=True).start()

    def _permission_answered(
        self, permission_id: str, allow: bool, error: Optional[Exception],
    ) -> None:
        row = self._permission_rows.pop(permission_id, None)
        if row is not None:
            row.destroy()
        if error:
            self._append("error", f"Не удалось ответить на MCP permission: {error}", remember=False)
        else:
            action = "разрешён один раз" if allow else "отклонён"
            self._append("activity", f"MCP-вызов {action}.", remember=False)

    def _finish(self, outcome: CopilotOutcome) -> None:
        self._cancel_event = None
        self._outcome = outcome
        self._outcome_model = self._running_model
        self._set_busy(False)
        self._clear_permissions()
        text = outcome.answer
        if outcome.question:
            text += "\n\nУточнение: " + outcome.question
        if outcome.warnings:
            text += "\n\nПредупреждения:\n• " + "\n• ".join(outcome.warnings)
        self._append("assistant", text)
        self._render_outcome(outcome)
        if (
            outcome.intent == "single_form"
            and outcome.selected_form_id is not None
            and outcome.context is not None
        ):
            form = FormRegistry().get(outcome.selected_form_id)
            self._status(
                f"Однозначно выбрана форма «{form.title}». Готовлю AI-заполнение…"
            )
            self.after(250, lambda: self._open_form(outcome.selected_form_id or ""))
        else:
            self._status("Готово. Любое действие ниже требует вашего явного выбора.")

    def _render_outcome(self, outcome: CopilotOutcome) -> None:
        self._clear_actions()
        if outcome.intent == "single_form":
            self._render_form_candidates(outcome)
        elif outcome.intent == "execution_plan":
            self._render_proposed_plan(outcome)
        elif outcome.intent in {"repository_search", "similar_objects"}:
            self._render_repository_items(outcome)
        elif outcome.intent == "diagnostics" and outcome.diagnostics is not None:
            self._render_diagnostics(outcome)

    def _render_form_candidates(self, outcome: CopilotOutcome) -> None:
        for candidate in outcome.form_candidates:
            form = FormRegistry().get(candidate.form_id)
            row = self._card(self._action_frame)
            tk.Label(
                row,
                text=f"{form.title}  ·  {candidate.score}/100\n{candidate.reason}",
                wraplength=570, justify=tk.LEFT, anchor="w", font=theme.F["small"],
                bg=theme.C["surface_alt"], fg=theme.C["text"],
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=7)
            button_text = "Открыть и заполнить" if outcome.context else "Открыть форму"
            ttk.Button(
                row, text=button_text,
                style=(
                    "Primary.TButton"
                    if candidate.form_id == outcome.selected_form_id
                    else "Secondary.TButton"
                ),
                command=lambda form_id=candidate.form_id: self._open_form(form_id),
            ).pack(side=tk.RIGHT, padx=8, pady=6)

    def _render_proposed_plan(self, outcome: CopilotOutcome) -> None:
        for step in outcome.plan:
            form = FormRegistry().get(step.form_id)
            deps = f" · после: {', '.join(step.depends_on)}" if step.depends_on else ""
            row = self._card(self._action_frame)
            tk.Label(
                row,
                text=(f"{step.position}. {step.title} — {form.title}\n"
                      f"{step.reason}{deps} · confidence: {step.confidence}"),
                wraplength=720, justify=tk.LEFT, anchor="w", font=theme.F["small"],
                bg=theme.C["surface_alt"], fg=theme.C["text"],
            ).pack(fill=tk.X, padx=10, pady=7)
        button = ttk.Button(
            self._action_frame, text="Принять план", style="Primary.TButton",
            command=self._accept_plan,
        )
        button.pack(anchor=tk.E, pady=(5, 0))
        if outcome.context is None:
            button.config(state=tk.DISABLED)
            tk.Label(
                self._action_frame,
                text="Не удалось подготовить безопасный контекст для шагов плана.",
                font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["warning"],
            ).pack(anchor=tk.E, pady=(2, 0))

    def _accept_plan(self) -> None:
        outcome = self._outcome
        if outcome is None or outcome.context is None or not outcome.plan:
            return
        current = self.app.execution_plan
        if current is not None and not show_confirm(
            self,
            "Заменить активный план",
            "Заменить текущий план новым? Подготовленные, но не отправленные "
            "данные старого плана будут потеряны.",
        ):
            return
        self.app.accept_execution_plan(
            context=outcome.context, steps=outcome.plan,
            title=(
                f"Заявка {outcome.context.ticket_id}"
                if outcome.context.ticket_id
                else "План из AI-чата"
            ),
            shared_guidance=self._outcome_guidance(outcome),
            provider_id=self._outcome_model[0],
            model_id=self._outcome_model[1],
            variant=self._outcome_model[2],
        )
        self._clear_actions()
        self._render_active_plan()
        self._append(
            "assistant",
            "План принят. Шаги открываются по очереди; каждый использует обычный "
            "AI-preview и требует ручной отправки формы.",
        )

    def _render_active_plan(self) -> None:
        for child in self._plan_frame.winfo_children():
            child.destroy()
        plan = self.app.execution_plan
        if plan is None:
            return
        head = tk.Frame(self._plan_frame, bg=theme.C["surface"])
        head.pack(fill=tk.X, pady=(2, 3))
        tk.Label(
            head, text=f"АКТИВНЫЙ ПЛАН · {plan.title}", font=theme.F["small"],
            bg=theme.C["surface"], fg=theme.C["success"] if plan.complete else theme.C["primary"],
        ).pack(side=tk.LEFT)
        if plan.complete:
            tk.Label(
                head, text="✓ завершён", font=theme.F["small"],
                bg=theme.C["surface"], fg=theme.C["success"],
            ).pack(side=tk.RIGHT)
        ttk.Button(
            head,
            text="Закрыть план" if plan.complete else "Отменить план",
            style="Ghost.TButton",
            command=lambda plan_id=plan.plan_id: self._clear_plan(plan_id),
        ).pack(side=tk.RIGHT, padx=(6, 0))
        labels = {
            "pending": "ожидает", "in_progress": "открыт",
            "prepared": "данные подготовлены", "completed": "выполнен", "failed": "ошибка",
        }
        for runtime in plan.snapshot():
            row = self._card(self._plan_frame)
            spec = runtime.spec
            tk.Label(
                row,
                text=(f"{spec.position}. {spec.title}\n{labels.get(runtime.status, runtime.status)}"
                      + (f" · {runtime.error}" if runtime.error else "")),
                wraplength=580, justify=tk.LEFT, anchor="w", font=theme.F["small"],
                bg=theme.C["surface_alt"],
                fg=theme.C["error"] if runtime.status == "failed" else theme.C["text"],
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=6)
            button = ttk.Button(
                row,
                text="Открыть шаг" if runtime.status != "prepared" else "Вернуться к шагу",
                style="Secondary.TButton",
                command=lambda step_id=spec.step_id: self._open_plan_step(step_id),
            )
            button.pack(side=tk.RIGHT, padx=8, pady=6)
            if not plan.can_open(spec.step_id):
                button.config(state=tk.DISABLED)

    def _open_plan_step(self, step_id: str) -> None:
        try:
            self.app.open_execution_plan_step(step_id)
        except Exception as exc:
            show_error(self, "План исполнения", str(exc))

    def _clear_plan(self, plan_id: str) -> None:
        plan = self.app.execution_plan
        if plan is None or plan.plan_id != plan_id:
            self._render_active_plan()
            return
        if not show_confirm(
            self,
            "План исполнения",
            "Закрыть завершённый план?"
            if plan.complete
            else "Отменить план? Подготовленные, но не отправленные данные будут потеряны.",
        ):
            return
        self.app.clear_execution_plan(plan_id)
        self._render_active_plan()
        self._append(
            "assistant",
            "План закрыт. Внешние системы не изменялись этим действием.",
        )

    def _render_repository_items(self, outcome: CopilotOutcome) -> None:
        for item in outcome.repository_items:
            row = self._card(self._action_frame)
            title = item.name or item.identifier or item.path
            identity = (
                f" [{item.identifier}]"
                if item.identifier and item.identifier != title
                else ""
            )
            tk.Label(
                row,
                text=(f"{item.entity_type.upper()} · {title}{identity} · {item.score}/100\n"
                      f"{item.reason}\nИсточник: {item.scope} · {item.path}"),
                wraplength=620, justify=tk.LEFT, anchor="w", font=theme.F["small"],
                bg=theme.C["surface_alt"], fg=theme.C["text"],
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=7)
            ttk.Button(
                row,
                text=(
                    "Использовать как шаблон"
                    if outcome.intent == "similar_objects"
                    else "Продолжить с объектом"
                ),
                style="Secondary.TButton",
                command=lambda value=item: self._continue_with_repository_item(value),
            ).pack(side=tk.RIGHT, padx=(0, 8), pady=6)

    def _render_diagnostics(self, outcome: CopilotOutcome) -> None:
        report = outcome.diagnostics
        if report is None:
            return
        for title, values in (
            ("Вероятные причины", report.probable_causes),
            ("Подтверждающие факты", report.evidence),
            ("Следующие действия", report.next_actions),
        ):
            if not values:
                continue
            row = self._card(self._action_frame)
            tk.Label(
                row, text=title + "\n• " + "\n• ".join(values),
                wraplength=750, justify=tk.LEFT, anchor="w", font=theme.F["small"],
                bg=theme.C["surface_alt"], fg=theme.C["text"],
            ).pack(fill=tk.X, padx=10, pady=7)
        if outcome.repository_items:
            self._render_repository_items(outcome)

    def _open_form(self, form_id: str) -> None:
        outcome = self._outcome
        if outcome is None or self._destroying:
            return
        if outcome.context is not None:
            self.app.open_ai_routed_form(
                form_id,
                outcome.context,
                guidance=self._outcome_guidance(outcome),
                provider_id=self._outcome_model[0],
                model_id=self._outcome_model[1],
                variant=self._outcome_model[2],
            )
            return
        from ui.screens.form_screen import FormScreen
        self.app.navigate_to(FormScreen, form_id=form_id)

    def _continue_with_repository_item(self, item) -> None:
        title = item.name or item.identifier or item.path
        action = (
            "Используй этот объект как проверяемый шаблон для заявки и выбери "
            "подходящую форму или план"
            if self._outcome is not None and self._outcome.intent == "similar_objects"
            else "Продолжи задачу с этим объектом и уточни требуемое действие"
        )
        self._start(
            f"{action}: {item.entity_type} {title}; scope={item.scope}; "
            f"x-filepath={item.path}. Не выполняй изменений без формы и подтверждения."
        )

    @staticmethod
    def _outcome_guidance(outcome: CopilotOutcome) -> str:
        """Передаёт extractor только валидированный итог, а не сырые MCP outputs."""
        payload = {
            "answer": outcome.answer,
            "selected_form_id": outcome.selected_form_id,
            "repository_items": [
                {
                    "entity_type": item.entity_type,
                    "identifier": item.identifier,
                    "name": item.name,
                    "scope": item.scope,
                    "path": item.path,
                    "reason": item.reason,
                }
                for item in outcome.repository_items
            ],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:20_000]

    def _fail(self, error: Exception) -> None:
        self._cancel_event = None
        self._set_busy(False)
        self._clear_permissions()
        if isinstance(error, OpenCodeCancelled):
            self._append("assistant", "Текущий запрос остановлен. Внешние системы не изменялись.")
            self._status("Запрос отменён.")
        else:
            _log.error(
                "unified copilot request failed error_type=%s session=%s",
                type(error).__name__,
                self._session_id or "unknown",
            )
            self._append("error", self._friendly_error(error))
            if self._session_id:
                self._status(
                    "Запрос завершился ошибкой. Сессия сохранена для диагностики.",
                    error=True,
                )
            else:
                self._status("Ошибка AI-помощника. Можно повторить запрос.", error=True)
            # Session остаётся активной: следующий запрос продолжит тот же
            # диалог и сможет опираться на уже сохранённый контекст.
            if self._copilot is not None:
                _log.info(
                    "failed copilot session preserved id=%s",
                    self._copilot.session_id or self._session_id or "unknown",
                )

    def _cancel_request(self) -> None:
        if not self._busy:
            return
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._status("Останавливаю запрос…")
        if self._copilot is not None:
            threading.Thread(
                target=self._copilot.cancel, name="opencode-copilot-abort", daemon=True,
            ).start()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._last_status_key = ""
        state = tk.DISABLED if busy else tk.NORMAL
        self._input.config(state=state)
        self._pick_button.config(state=state)
        self._send_button.config(state=state)
        if busy:
            self._status_panel.config(bg=theme.C["chat_status"])
            self._status_dot.pack_forget()
            self._spinner.config(bg=theme.C["chat_status"])
            self._spinner.pack(
                side=tk.LEFT,
                padx=(9, 5),
                pady=5,
                before=self._status_label,
            )
            self._start_spinner()
            self._status_label.config(bg=theme.C["chat_status"])
            self._cancel_button.pack(side=tk.RIGHT, padx=6, pady=2)
        else:
            self._cancel_button.pack_forget()
            self._stop_spinner()
            self._spinner.pack_forget()
            if not self._status_dot.winfo_ismapped():
                self._status_dot.pack(
                    side=tk.LEFT,
                    padx=(10, 6),
                    pady=7,
                    before=self._status_label,
                )
        self._set_model_controls_enabled(True)

    def _start_spinner(self) -> None:
        if self._spinner_after_id is None and not self._destroying:
            self._animate_spinner()

    def _animate_spinner(self) -> None:
        self._spinner_after_id = None
        if not self._busy or self._destroying:
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
        self._spinner_after_id = self.after(55, self._animate_spinner)

    def _stop_spinner(self) -> None:
        if self._spinner_after_id is not None:
            try:
                self.after_cancel(self._spinner_after_id)
            except tk.TclError:
                pass
            self._spinner_after_id = None
        self._spinner.delete("all")

    def _status(self, message: str, *, error: bool = False) -> None:
        self._status_var.set(message)
        background = theme.C["chat_error"] if error else theme.C["chat_status"]
        self._status_panel.config(bg=background)
        self._spinner.config(bg=background)
        self._status_dot.config(
            bg=background,
            fg=theme.C["error"] if error else (
                theme.C["primary"] if self._busy else theme.C["success"]
            ),
        )
        self._status_label.config(
            bg=background,
            fg=theme.C["error"] if error else theme.C["text_label"],
        )

    def _append(self, role: str, message: str, *, remember: bool = True) -> None:
        clean = str(message).strip()
        if not clean:
            return
        self._transcript.config(state=tk.NORMAL)
        if role == "activity":
            self._transcript.insert(tk.END, f"⚙  {clean}\n", "activity")
        else:
            labels = {"assistant": "GRAVITEE AI", "user": "ВЫ", "error": "ОШИБКА"}
            timestamp = datetime.now().strftime("%H:%M")
            meta_tag = f"{role}_meta" if role in {"assistant", "user", "error"} else "assistant_meta"
            body_tag = role if role in {"assistant", "user", "error"} else "assistant"
            self._transcript.insert(
                tk.END,
                f"{labels.get(role, str(role).upper())}  ·  {timestamp}\n",
                meta_tag,
            )
            self._transcript.insert(tk.END, clean + "\n", body_tag)
        self._transcript.config(state=tk.DISABLED)
        self._transcript.see(tk.END)
        if remember and role in {"assistant", "user", "error"}:
            self.app.add_copilot_history(role, clean)

    @staticmethod
    def _friendly_error(error: Exception) -> str:
        message = str(error).strip()
        if "Internal Server Error" in message or "InternalServerError" in message:
            return (
                "Provider вернул HTTP 500 и не передал описание причины. "
                "Сессия сохранена: откройте её кнопкой в шапке, чтобы увидеть "
                "ход выполнения и повторные попытки OpenCode."
            )
        if "Expected OutputFormatJsonSchema" in message:
            return (
                "OpenCode не смог повторно прочитать сообщение со Structured Output. "
                "Это ошибка сериализации session в OpenCode 1.18.18; исходная "
                "сессия сохранена для просмотра."
            )
        if len(message) > 700:
            message = message[:697].rstrip() + "…"
        return "Не удалось обработать запрос: " + message

    def _set_session(self, session_id: str) -> None:
        self._session_id = session_id.strip()
        if self._session_id:
            self._session_button.config(
                text=f"Сессия …{self._session_id[-8:]}  ↗"
            )
            if not self._session_button.winfo_ismapped():
                self._session_button.pack(side=tk.RIGHT, padx=(0, 8))
            _log.info("home copilot session=%s", self._session_id)
        else:
            self._session_button.pack_forget()

    def _open_session_in_browser(self) -> None:
        if not self._session_id:
            self._status("OpenCode session ещё не создана.", error=True)
            return
        client = self.app.opencode_manager.client
        if client is None:
            self._status("Сначала восстановите подключение к OpenCode Server.", error=True)
            return
        try:
            url = client.session_web_url(self._session_id)
            opened = webbrowser.open(url, new=2)
        except Exception as exc:
            _log.warning("failed to open session in browser", exc_info=True)
            self._status(f"Не удалось открыть OpenCode Web: {exc}", error=True)
            return
        if opened:
            self._status("Сессия открыта в OpenCode Web.")
        else:
            self._status(
                "Браузер не открылся автоматически. Откройте адрес OpenCode Server вручную.",
                error=True,
            )

    def _clear_actions(self) -> None:
        for child in self._action_frame.winfo_children():
            child.destroy()

    def _clear_permissions(self) -> None:
        for row in self._permission_rows.values():
            try:
                row.destroy()
            except tk.TclError:
                pass
        self._permission_rows.clear()

    @staticmethod
    def _card(parent: tk.Widget) -> tk.Frame:
        row = tk.Frame(parent, bg=theme.C["surface_alt"])
        row.pack(fill=tk.X, pady=2)
        return row

    def _set_input(self, value: str) -> None:
        if self._busy:
            return
        self._input.delete("1.0", tk.END)
        self._input.insert("1.0", value)
        self._input.focus_set()
        self._input.mark_set(tk.INSERT, tk.END)

    @staticmethod
    def _parse_mcp(value: str) -> list[str]:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            parsed = value.split(",")
        if not isinstance(parsed, list):
            return []
        return list(dict.fromkeys(str(item).strip() for item in parsed if str(item).strip()))

    def detach_for_shutdown(self) -> Optional[UnifiedCopilot]:
        self._destroying = True
        self._stop_spinner()
        if self._cancel_event is not None:
            self._cancel_event.set()
        copilot = self._copilot
        self._copilot = None
        if getattr(self.app, "home_copilot", None) is copilot:
            self.app.home_copilot = None
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        return copilot

    def detach_for_navigation(self) -> None:
        """Отделяет Tk-виджет, сохраняя долгоживущую OpenCode session в app."""
        self._destroying = True
        self._stop_spinner()
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        if self._busy and self._cancel_event is not None:
            self._cancel_event.set()
            if self._copilot is not None:
                threading.Thread(
                    target=self._copilot.cancel,
                    name="opencode-home-navigation-abort",
                    daemon=True,
                ).start()

    def shutdown(self) -> None:
        copilot = self.detach_for_shutdown()
        if copilot is not None:
            def cleanup() -> None:
                copilot.cancel()
                copilot.close()
            threading.Thread(
                target=cleanup, name="opencode-home-chat-cleanup", daemon=True,
            ).start()
