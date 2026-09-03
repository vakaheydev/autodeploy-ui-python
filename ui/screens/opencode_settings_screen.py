"""Настройки общего OpenCode Server, MCP и встроенный технический журнал."""
from __future__ import annotations

import json
import math
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional

import ui.theme as theme
from config.environments import (
    OPENCODE_ALLOWED_MCP_KEY,
    OPENCODE_CONNECT_TIMEOUT_KEY,
    OPENCODE_MAX_CONTEXT_CHARS_KEY,
    OPENCODE_MODEL_ID_KEY,
    OPENCODE_PROVIDER_ID_KEY,
    OPENCODE_REQUEST_TIMEOUT_KEY,
    OPENCODE_SERVER_PASSWORD_KEY,
    OPENCODE_SERVER_URL_KEY,
    OPENCODE_SERVER_USERNAME_KEY,
    OPENCODE_STARTUP_TIMEOUT_KEY,
)
from core.logging_setup import UI_LOG_BUFFER
from opencode_integration.manager import (
    DEFAULT_SERVER_URL,
    REQUIRED_AGENTS,
    TARGET_OPENCODE_VERSION,
)
from ui.dialogs import show_error, show_info
from ui.screens.base_screen import BaseScreen


class OpenCodeSettingsScreen(BaseScreen):
    def __init__(self, master, app, **kwargs) -> None:
        self._vars: Dict[str, tk.StringVar] = {}
        self._mcp_vars: Dict[str, tk.BooleanVar] = {}
        self._saved_mcp: set[str] = set()
        self._busy = False
        self._poll_id: Optional[str] = None
        self._log_sequence = 0
        self._worker_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        super().__init__(master, app, **kwargs)

    def _build(self) -> None:
        self._add_back_button()
        self._add_title("OpenCode")
        theme.separator(self, pady=6)

        wrap = tk.Frame(self, bg=theme.C["bg"])
        wrap.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(wrap, bg=theme.C["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=canvas.yview)
        col = tk.Frame(canvas, bg=theme.C["bg"])
        col.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=col, anchor="nw")
        canvas.bind("<Configure>", self._centered_resize(canvas, window_id, max_width=900))
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.bind(
            "<MouseWheel>",
            lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"),
        )

        saved = self.app.env_manager.load()
        self._build_status_card(col)
        self._build_primary_actions(col)
        self._build_connection_settings(col, saved)
        self._build_ai_settings(col, saved)
        self._build_mcp_card(col, saved)
        self._build_terminal(col)

        self.bind("<Destroy>", self._on_destroy)
        self._refresh()

    def _build_status_card(self, parent: tk.Widget) -> None:
        card = theme.card(parent, pady=4)
        top = tk.Frame(card, bg=theme.C["surface"])
        top.pack(fill=tk.X, padx=16, pady=(12, 4))
        tk.Label(
            top,
            text="СОСТОЯНИЕ СЕРВЕРА",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT)
        self._check_btn = ttk.Button(
            top,
            text="Проверить состояние сервера",
            style="Secondary.TButton",
            command=lambda: self._run_manager_action("check"),
        )
        self._check_btn.pack(side=tk.RIGHT)

        self._status_var = tk.StringVar(value="OpenCode Server не подключён")
        self._detail_var = tk.StringVar()
        self._status_label = tk.Label(
            card,
            textvariable=self._status_var,
            font=theme.F["h2"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            justify=tk.LEFT,
            anchor="w",
        )
        self._status_label.pack(fill=tk.X, padx=16, pady=(4, 2))
        tk.Label(
            card,
            textvariable=self._detail_var,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 12))

    def _build_primary_actions(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, bg=theme.C["bg"])
        row.pack(fill=tk.X, pady=8)
        row.columnconfigure(0, weight=1, uniform="server-action")
        row.columnconfigure(1, weight=1, uniform="server-action")

        connect_border = tk.Frame(row, bg=theme.C["border"])
        connect_border.grid(row=0, column=0, sticky="nsew", padx=(2, 5))
        connect = tk.Frame(connect_border, bg=theme.C["surface"])
        connect.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(
            connect,
            text="Подключиться к серверу",
            font=theme.F["h2"],
            bg=theme.C["surface"],
            fg=theme.C["text"],
        ).pack(anchor=tk.W, padx=16, pady=(14, 4))
        tk.Label(
            connect,
            text=(
                "Использовать уже работающий OpenCode Server. "
                "Форма не будет останавливать его при закрытии."
            ),
            wraplength=390,
            justify=tk.LEFT,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(fill=tk.X, padx=16, pady=(0, 12))
        self._connect_btn = ttk.Button(
            connect,
            text="Подключиться к серверу",
            style="Hero.TButton",
            command=lambda: self._run_manager_action("connect"),
        )
        self._connect_btn.pack(fill=tk.X, padx=16, pady=(0, 16))

        create_border = tk.Frame(row, bg=theme.C["border"])
        create_border.grid(row=0, column=1, sticky="nsew", padx=(5, 2))
        create = tk.Frame(create_border, bg=theme.C["surface"])
        create.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(
            create,
            text="Создать новый сервер",
            font=theme.F["h2"],
            bg=theme.C["surface"],
            fg=theme.C["text"],
        ).pack(anchor=tk.W, padx=16, pady=(14, 4))
        tk.Label(
            create,
            text=(
                "Запустить opencode serve на свободном localhost-порту "
                "в изолированной runtime-директории."
            ),
            wraplength=390,
            justify=tk.LEFT,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(fill=tk.X, padx=16, pady=(0, 12))
        self._create_btn = ttk.Button(
            create,
            text="Создать новый сервер",
            style="HeroSecondary.TButton",
            command=lambda: self._run_manager_action("create"),
        )
        self._create_btn.pack(fill=tk.X, padx=16, pady=(0, 10))

        controls = tk.Frame(create, bg=theme.C["surface"])
        controls.pack(fill=tk.X, padx=16, pady=(0, 16))
        self._restart_btn = ttk.Button(
            controls,
            text="Перезапустить",
            style="Secondary.TButton",
            command=lambda: self._run_manager_action("restart"),
        )
        self._restart_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._stop_btn = ttk.Button(
            controls,
            text="Остановить / отключить",
            style="Secondary.TButton",
            command=lambda: self._run_manager_action("stop"),
        )
        self._stop_btn.pack(side=tk.LEFT)

    def _build_connection_settings(
        self,
        parent: tk.Widget,
        saved: Dict[str, str],
    ) -> None:
        card = theme.card(parent, pady=8)
        tk.Label(
            card,
            text="ПОДКЛЮЧЕНИЕ",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=16, pady=(10, 5))
        grid = tk.Frame(card, bg=theme.C["surface"])
        grid.pack(fill=tk.X, padx=16, pady=(0, 8))
        rows = [
            (OPENCODE_SERVER_URL_KEY, "Адрес сервера", DEFAULT_SERVER_URL, False),
            (OPENCODE_CONNECT_TIMEOUT_KEY, "Connect timeout, sec", "10", False),
            (OPENCODE_SERVER_USERNAME_KEY, "Basic Auth username", "opencode", False),
            (OPENCODE_SERVER_PASSWORD_KEY, "Basic Auth password", "", True),
        ]
        for index, (key, label, default, secret) in enumerate(rows):
            var = tk.StringVar(value=saved.get(key, default))
            self._vars[key] = var
            tk.Label(
                grid,
                text=label,
                width=24,
                anchor="w",
                font=theme.F["body"],
                bg=theme.C["surface"],
                fg=theme.C["text_label"],
            ).grid(row=index, column=0, sticky="w", pady=3)
            entry = self._entry(grid, var, secret=secret)
            entry.grid(row=index, column=1, sticky="ew", padx=(8, 0), pady=3)
        grid.columnconfigure(1, weight=1)
        tk.Label(
            card,
            text=(
                "При старте форма автоматически пытается подключиться по этому адресу. "
                "Допустим только http://127.0.0.1:<port>."
            ),
            wraplength=820,
            justify=tk.LEFT,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

    def _build_ai_settings(self, parent: tk.Widget, saved: Dict[str, str]) -> None:
        card = theme.card(parent, pady=8)
        tk.Label(
            card,
            text="СОЗДАНИЕ СЕРВЕРА И AI",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=16, pady=(10, 5))
        grid = tk.Frame(card, bg=theme.C["surface"])
        grid.pack(fill=tk.X, padx=16, pady=(0, 8))
        rows = [
            (OPENCODE_PROVIDER_ID_KEY, "Provider ID", ""),
            (OPENCODE_MODEL_ID_KEY, "Model ID", ""),
            (OPENCODE_STARTUP_TIMEOUT_KEY, "Startup timeout, sec", "20"),
            (OPENCODE_REQUEST_TIMEOUT_KEY, "Request timeout, sec", "120"),
            (OPENCODE_MAX_CONTEXT_CHARS_KEY, "Max context chars", "120000"),
        ]
        for index, (key, label, default) in enumerate(rows):
            var = tk.StringVar(value=saved.get(key, default))
            self._vars[key] = var
            tk.Label(
                grid,
                text=label,
                width=24,
                anchor="w",
                font=theme.F["body"],
                bg=theme.C["surface"],
                fg=theme.C["text_label"],
            ).grid(row=index, column=0, sticky="w", pady=3)
            self._entry(grid, var).grid(
                row=index, column=1, sticky="ew", padx=(8, 0), pady=3
            )
        grid.columnconfigure(1, weight=1)

        actions = tk.Frame(card, bg=theme.C["surface"])
        actions.pack(fill=tk.X, padx=16, pady=(0, 12))
        ttk.Button(
            actions,
            text="Сохранить настройки",
            style="Primary.TButton",
            command=self._save,
        ).pack(side=tk.LEFT, padx=(0, 6))
        self._provider_btn = ttk.Button(
            actions,
            text="Проверить provider",
            style="Secondary.TButton",
            command=self._check_provider,
        )
        self._provider_btn.pack(side=tk.LEFT)
        self._provider_var = tk.StringVar(value="Provider: не проверен")
        tk.Label(
            actions,
            textvariable=self._provider_var,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT, padx=10)

    def _build_mcp_card(self, parent: tk.Widget, saved: Dict[str, str]) -> None:
        card = theme.card(parent, pady=8)
        head = tk.Frame(card, bg=theme.C["surface"])
        head.pack(fill=tk.X, padx=16, pady=(10, 5))
        tk.Label(
            head,
            text="MCP ДЛЯ АГЕНТА ФОРМЫ",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT)
        self._mcp_refresh_btn = ttk.Button(
            head,
            text="Обновить список MCP",
            style="Secondary.TButton",
            command=self._load_mcp,
        )
        self._mcp_refresh_btn.pack(side=tk.RIGHT)
        self._saved_mcp = self._parse_mcp(saved.get(OPENCODE_ALLOWED_MCP_KEY, ""))
        self._mcp_info = tk.StringVar(
            value="Подключитесь к серверу и обновите список."
        )
        tk.Label(
            card,
            textvariable=self._mcp_info,
            wraplength=820,
            justify=tk.LEFT,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(fill=tk.X, padx=16, pady=(0, 5))
        self._mcp_frame = tk.Frame(card, bg=theme.C["surface"])
        self._mcp_frame.pack(fill=tk.X, padx=16, pady=(0, 12))

    def _build_terminal(self, parent: tk.Widget) -> None:
        card = theme.card(parent, pady=8)
        head = tk.Frame(card, bg=theme.C["surface"])
        head.pack(fill=tk.X, padx=16, pady=(10, 5))
        tk.Label(
            head,
            text="ЖУРНАЛ OPENCODE",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT)
        ttk.Button(
            head,
            text="Очистить экран",
            style="Ghost.TButton",
            command=self._clear_terminal,
        ).pack(side=tk.RIGHT)
        self._terminal = tk.Text(
            card,
            height=13,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#0F172A",
            fg="#CBD5E1",
            insertbackground="#FFFFFF",
            relief="flat",
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )
        self._terminal.pack(fill=tk.X, padx=16, pady=(0, 5))
        tk.Label(
            card,
            text=f"Ротационный файл: {self.app.log_path}",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 10))

    def _entry(
        self,
        parent: tk.Widget,
        variable: tk.StringVar,
        *,
        secret: bool = False,
    ) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            show="*" if secret else "",
            bg=theme.C["input_bg"],
            fg=theme.C["text"],
            relief="solid",
            bd=1,
            font=theme.F["body"],
            insertbackground=theme.C["text"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )

    def _refresh(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._drain_workers()
        status = self.app.opencode_manager.status
        labels = {
            "ready": "● OpenCode готов",
            "connecting": "● Подключение…",
            "starting": "● Создание сервера…",
            "checking": "● Проверка сервера…",
            "error": "● OpenCode недоступен",
            "stopped": "○ OpenCode отключён",
        }
        colors = {
            "ready": theme.C["success"],
            "connecting": theme.C["warning"],
            "starting": theme.C["warning"],
            "checking": theme.C["warning"],
            "error": theme.C["error"],
            "stopped": theme.C["text_muted"],
        }
        self._status_var.set(labels.get(status.state, status.state))
        self._status_label.config(fg=colors.get(status.state, theme.C["text_muted"]))
        detail = [status.message]
        if status.version:
            note = "" if status.version == TARGET_OPENCODE_VERSION else (
                f" — ожидается {TARGET_OPENCODE_VERSION}"
            )
            detail.append(f"Версия: {status.version}{note}")
        if status.address:
            detail.append(f"Адрес: {status.address}")
        detail.append(
            "Режим: "
            + {
                "external": "подключение к внешнему серверу",
                "owned": "сервер создан формой",
                "none": "не подключено",
            }.get(status.ownership, status.ownership)
        )
        if status.pid is not None:
            detail.append(f"PID: {status.pid}")
        agents = ", ".join(REQUIRED_AGENTS)
        detail.append(
            f"Агенты {agents}: "
            f"{'загружены' if status.agent_loaded else 'не проверены'}"
        )
        detail.append(f"Runtime: {status.runtime_dir}")
        self._detail_var.set("\n".join(detail))
        self._refresh_logs()

        state = tk.DISABLED if self._busy else tk.NORMAL
        for button in (
            self._connect_btn,
            self._create_btn,
            self._check_btn,
            self._provider_btn,
            self._mcp_refresh_btn,
            self._stop_btn,
        ):
            button.config(state=state)
        self._restart_btn.config(
            state=(
                tk.NORMAL
                if not self._busy and status.ownership == "owned"
                else tk.DISABLED
            )
        )
        self._poll_id = self.after(250, self._refresh)

    def _drain_workers(self) -> None:
        try:
            while True:
                event, payload = self._worker_queue.get_nowait()
                if event == "manager":
                    self._busy = False
                    if isinstance(payload, Exception):
                        show_error(self, "OpenCode", str(payload))
                elif event == "provider":
                    self._provider_var.set(str(payload))
                elif event == "mcp":
                    self._render_mcp(payload)
        except queue.Empty:
            return

    def _run_manager_action(self, action: str) -> None:
        if self._busy:
            return
        # Проверка и отключение должны оставаться доступны, даже если в ещё не
        # сохранённом поле настроек сейчас опечатка. Новые значения применяем
        # только к явным операциям connect/create.
        if action in {"connect", "create"}:
            try:
                self._apply_settings(save=True)
            except ValueError as exc:
                show_error(self, "Некорректные настройки", str(exc))
                return
        self._busy = True

        def worker() -> None:
            try:
                manager = self.app.opencode_manager
                if action == "connect":
                    manager.connect()
                elif action == "create":
                    manager.create()
                elif action == "restart":
                    manager.restart()
                elif action == "stop":
                    manager.stop()
                elif action == "check":
                    manager.check_status()
            except Exception as exc:
                self._worker_queue.put(("manager", exc))
            else:
                self._worker_queue.put(("manager", None))

        threading.Thread(
            target=worker,
            name=f"opencode-ui-{action}",
            daemon=True,
        ).start()

    def _check_provider(self) -> None:
        client = self.app.opencode_manager.client
        if client is None:
            show_error(self, "OpenCode", "Сервер ещё не подключён")
            return
        provider_id = self._vars[OPENCODE_PROVIDER_ID_KEY].get().strip()
        self._provider_var.set("Provider: проверяю…")

        def worker() -> None:
            try:
                client.require_provider(
                    provider_id,
                    timeout=min(10.0, max(0.5, client.timeout)),
                )
            except Exception as exc:
                label = f"Provider: ошибка — {exc}"
            else:
                label = f"Provider: готов ({provider_id or 'OpenCode default'})"
            self._worker_queue.put(("provider", label))

        threading.Thread(
            target=worker,
            name="opencode-provider-check",
            daemon=True,
        ).start()

    def _load_mcp(self) -> None:
        client = self.app.opencode_manager.client
        if client is None:
            show_error(self, "OpenCode", "Сначала подключитесь к серверу")
            return
        self._mcp_info.set("Получаю список MCP из глобальной конфигурации OpenCode…")

        def worker() -> None:
            try:
                value: object = client.list_mcp_servers(timeout=10.0)
            except Exception as exc:
                value = exc
            self._worker_queue.put(("mcp", value))

        threading.Thread(target=worker, name="opencode-mcp-list", daemon=True).start()

    def _render_mcp(self, payload: object) -> None:
        if isinstance(payload, Exception):
            self._mcp_info.set(f"Не удалось получить MCP: {payload}")
            return
        statuses = payload if isinstance(payload, dict) else {}
        for child in self._mcp_frame.winfo_children():
            child.destroy()
        self._mcp_vars.clear()
        if not statuses:
            self._mcp_info.set("Глобальные MCP не настроены для runtime формы.")
            return
        connected = 0
        for name in sorted(statuses):
            status_obj = statuses[name] if isinstance(statuses[name], dict) else {}
            status = str(status_obj.get("status", "unknown"))
            enabled = status == "connected"
            connected += int(enabled)
            var = tk.BooleanVar(value=enabled and name in self._saved_mcp)
            self._mcp_vars[name] = var
            checkbox = ttk.Checkbutton(
                self._mcp_frame,
                text=f"{name}  ·  {status}",
                variable=var,
                command=self._sync_mcp_selection,
            )
            checkbox.pack(anchor=tk.W, pady=2)
            if not enabled:
                checkbox.config(state=tk.DISABLED)
        self._mcp_info.set(
            f"Найдено MCP: {len(statuses)}, подключено: {connected}. "
            "Read-only вызовы потребуют подтверждения; изменяющие операции запрещены."
        )

    def _sync_mcp_selection(self) -> None:
        # До первого GET /mcp виджеты ещё не созданы: в этот момент connect/save
        # не должны молча стирать ранее сохранённый allowlist.
        if not self._mcp_vars:
            return
        self._saved_mcp = {
            name for name, variable in self._mcp_vars.items() if variable.get()
        }

    def _save(self) -> None:
        try:
            self._apply_settings(save=True)
        except ValueError as exc:
            show_error(self, "Некорректные настройки", str(exc))
            return
        show_info(
            self,
            "OpenCode",
            "Настройки сохранены. Новые permissions применятся к следующей session; "
            "после изменения URL или Basic Auth переподключитесь к серверу.",
        )

    def _apply_settings(self, *, save: bool) -> None:
        try:
            connect_timeout = float(
                self._vars[OPENCODE_CONNECT_TIMEOUT_KEY].get()
            )
            startup_timeout = float(
                self._vars[OPENCODE_STARTUP_TIMEOUT_KEY].get()
            )
            request_timeout = float(
                self._vars[OPENCODE_REQUEST_TIMEOUT_KEY].get()
            )
            max_context = int(
                self._vars[OPENCODE_MAX_CONTEXT_CHARS_KEY].get()
            )
        except ValueError as exc:
            raise ValueError("Timeout и max context должны быть числами.") from exc
        timeouts = (connect_timeout, startup_timeout, request_timeout)
        if any(not math.isfinite(value) or value <= 0 for value in timeouts):
            raise ValueError("Timeout должен быть положительным конечным числом.")
        if not 10_000 <= max_context <= 500_000:
            raise ValueError("Max context должен быть от 10000 до 500000.")
        provider = self._vars[OPENCODE_PROVIDER_ID_KEY].get().strip()
        model = self._vars[OPENCODE_MODEL_ID_KEY].get().strip()
        if bool(provider) != bool(model):
            raise ValueError("Provider ID и Model ID задаются вместе.")
        address = self._vars[OPENCODE_SERVER_URL_KEY].get().strip()
        username = self._vars[OPENCODE_SERVER_USERNAME_KEY].get().strip()
        password = self._vars[OPENCODE_SERVER_PASSWORD_KEY].get()
        self.app.opencode_manager.configure(
            server_url=address,
            connect_timeout=connect_timeout,
            startup_timeout=startup_timeout,
            request_timeout=request_timeout,
            username=username,
            password=password,
        )
        if save:
            self._sync_mcp_selection()
            values = {key: variable.get().strip() for key, variable in self._vars.items()}
            # У password пробелы могут быть значимы.
            values[OPENCODE_SERVER_PASSWORD_KEY] = password
            values[OPENCODE_ALLOWED_MCP_KEY] = json.dumps(
                sorted(self._saved_mcp),
                ensure_ascii=False,
            )
            self.app.env_manager.save(values)

    def _refresh_logs(self) -> None:
        entries = UI_LOG_BUFFER.since(self._log_sequence)
        if not entries:
            return
        self._terminal.config(state=tk.NORMAL)
        for entry in entries:
            self._terminal.insert(tk.END, entry.text + "\n")
            self._log_sequence = max(self._log_sequence, entry.sequence)
        line_count = int(self._terminal.index("end-1c").split(".")[0])
        if line_count > 1000:
            self._terminal.delete("1.0", f"{line_count - 900}.0")
        self._terminal.see(tk.END)
        self._terminal.config(state=tk.DISABLED)

    def _clear_terminal(self) -> None:
        self._terminal.config(state=tk.NORMAL)
        self._terminal.delete("1.0", tk.END)
        self._terminal.config(state=tk.DISABLED)

    @staticmethod
    def _parse_mcp(value: str) -> set[str]:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            parsed = [item.strip() for item in value.split(",")]
        return {
            str(item).strip()
            for item in parsed
            if str(item).strip()
        } if isinstance(parsed, list) else set()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self and self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
