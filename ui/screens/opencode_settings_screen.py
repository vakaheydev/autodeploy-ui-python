"""Отдельный экран настроек и диагностики локального OpenCode Server."""
from __future__ import annotations

import threading
import queue
import tkinter as tk
from tkinter import ttk
from typing import Dict

import ui.theme as theme
from config.environments import (
    OPENCODE_MAX_CONTEXT_CHARS_KEY,
    OPENCODE_MODEL_ID_KEY,
    OPENCODE_PROVIDER_ID_KEY,
    OPENCODE_REQUEST_TIMEOUT_KEY,
    OPENCODE_STARTUP_TIMEOUT_KEY,
)
from opencode_integration.manager import (
    FORM_EXTRACTOR_AGENT,
    TARGET_OPENCODE_VERSION,
)
from ui.dialogs import show_error, show_info
from ui.screens.base_screen import BaseScreen


class OpenCodeSettingsScreen(BaseScreen):
    def __init__(self, master, app, **kwargs) -> None:
        self._vars: Dict[str, tk.StringVar] = {}
        self._busy = False
        self._poll_id = None
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
        canvas.bind(
            "<Configure>", self._centered_resize(canvas, window_id, max_width=760)
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        status_card = theme.card(col, pady=4)
        tk.Label(
            status_card,
            text="СОСТОЯНИЕ ЛОКАЛЬНОГО СЕРВЕРА",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 6))
        self._status_var = tk.StringVar()
        self._detail_var = tk.StringVar()
        self._provider_var = tk.StringVar(value="Provider: не проверен")
        self._status_label = tk.Label(
            status_card,
            textvariable=self._status_var,
            font=theme.F["h3"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            anchor="w",
        )
        self._status_label.pack(fill=tk.X, padx=14)
        tk.Label(
            status_card,
            textvariable=self._detail_var,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(3, 0))
        tk.Label(
            status_card,
            textvariable=self._provider_var,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(2, 8))

        action_row = tk.Frame(status_card, bg=theme.C["surface"])
        action_row.pack(fill=tk.X, padx=14, pady=(0, 12))
        self._start_btn = ttk.Button(
            action_row, text="Запустить / проверить", style="Primary.TButton",
            command=lambda: self._run_manager_action("start"),
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._restart_btn = ttk.Button(
            action_row, text="Перезапустить", style="Secondary.TButton",
            command=lambda: self._run_manager_action("restart"),
        )
        self._restart_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._stop_btn = ttk.Button(
            action_row, text="Остановить", style="Secondary.TButton",
            command=lambda: self._run_manager_action("stop"),
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            action_row, text="Проверить provider", style="Secondary.TButton",
            command=self._check_provider,
        ).pack(side=tk.LEFT)

        settings_card = theme.card(col, pady=10)
        tk.Label(
            settings_card,
            text="НАСТРОЙКИ AI-ИЗВЛЕЧЕНИЯ",
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 4))
        tk.Label(
            settings_card,
            text=(
                "Provider credentials настраиваются в самом OpenCode и здесь не сохраняются. "
                "Пустые Provider/Model используют модель OpenCode по умолчанию."
            ),
            wraplength=690,
            justify=tk.LEFT,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(0, 8))

        saved = self.app.env_manager.load()
        grid = tk.Frame(settings_card, bg=theme.C["surface"])
        grid.pack(fill=tk.X, padx=14, pady=(0, 10))
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
                grid, text=label, width=23, anchor="w",
                font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_label"],
            ).grid(row=index, column=0, sticky="w", pady=3)
            entry = tk.Entry(
                grid, textvariable=var,
                bg=theme.C["input_bg"], fg=theme.C["text"],
                relief="solid", bd=1, font=theme.F["body"],
                insertbackground=theme.C["text"], highlightthickness=1,
                highlightbackground=theme.C["input_border"],
                highlightcolor=theme.C["border_focus"],
            )
            entry.grid(row=index, column=1, sticky="ew", padx=(8, 0), pady=3)
        grid.columnconfigure(1, weight=1)

        ttk.Button(
            settings_card, text="Сохранить", style="Primary.TButton", command=self._save,
        ).pack(anchor=tk.W, padx=14, pady=(0, 12))

        info_card = theme.card(col, pady=4)
        tk.Label(
            info_card,
            text=(
                f"Команда: opencode · целевая версия: {TARGET_OPENCODE_VERSION}\n"
                f"Агент: {FORM_EXTRACTOR_AGENT} · bind: 127.0.0.1 (фиксировано)"
            ),
            justify=tk.LEFT,
            font=theme.F["small"],
            bg=theme.C["surface"],
            fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=10)

        self.bind("<Destroy>", self._on_destroy)
        self._refresh_status()

    def _refresh_status(self) -> None:
        try:
            exists = bool(self.winfo_exists())
        except tk.TclError:
            return
        if not exists:
            return
        # Забираем результаты worker threads только из Tk thread.
        try:
            while True:
                event, payload = self._worker_queue.get_nowait()
                if event == "manager":
                    self._finish_action(payload if isinstance(payload, Exception) else None)
                elif event == "provider":
                    self._provider_var.set(str(payload))
        except queue.Empty:
            pass
        status = self.app.opencode_manager.status
        labels = {
            "ready": "✓ OpenCode готов",
            "starting": "… OpenCode запускается",
            "error": "✗ OpenCode недоступен",
            "stopped": "○ OpenCode остановлен",
        }
        colors = {
            "ready": theme.C["success"],
            "error": theme.C["error"],
            "starting": theme.C["warning"],
            "stopped": theme.C["text_muted"],
        }
        self._status_var.set(labels.get(status.state, status.state))
        self._status_label.config(fg=colors.get(status.state, theme.C["text_muted"]))
        details = [status.message]
        if status.version:
            version_note = "" if status.version == TARGET_OPENCODE_VERSION else " (ожидалась 1.18.18)"
            details.append(f"Версия: {status.version}{version_note}")
        if status.address:
            details.append(f"Адрес: {status.address}")
        if status.pid is not None:
            details.append(f"PID: {status.pid}")
        details.append(f"Агент загружен: {'да' if status.agent_loaded else 'нет'}")
        self._detail_var.set("\n".join(details))
        state = tk.DISABLED if self._busy else tk.NORMAL
        for button in (self._start_btn, self._restart_btn, self._stop_btn):
            button.config(state=state)
        self._poll_id = self.after(500, self._refresh_status)

    def _run_manager_action(self, action: str) -> None:
        if self._busy:
            return
        self._busy = True

        def worker() -> None:
            try:
                manager = self.app.opencode_manager
                if action == "stop":
                    manager.stop()
                elif action == "restart":
                    manager.restart()
                else:
                    manager.start()
            except Exception as exc:
                self._worker_queue.put(("manager", exc))
            else:
                self._worker_queue.put(("manager", None))

        threading.Thread(target=worker, name=f"opencode-{action}", daemon=True).start()

    def _finish_action(self, error: Exception | None) -> None:
        self._busy = False
        if error is not None:
            show_error(self, "OpenCode", str(error))

    def _check_provider(self) -> None:
        client = self.app.opencode_manager.client
        if client is None:
            show_error(self, "OpenCode", "Сервер ещё не готов")
            return
        provider_id = self._vars[OPENCODE_PROVIDER_ID_KEY].get().strip()
        self._provider_var.set("Provider: проверяю...")

        def worker() -> None:
            try:
                client.require_provider(
                    provider_id, timeout=min(10.0, max(0.5, client.timeout))
                )
            except Exception as exc:
                self._worker_queue.put(("provider", f"Provider: ошибка — {exc}"))
            else:
                label = provider_id or "OpenCode default"
                self._worker_queue.put(("provider", f"Provider: готов ({label})"))

        threading.Thread(target=worker, name="opencode-provider-check", daemon=True).start()

    def _save(self) -> None:
        try:
            startup = float(self._vars[OPENCODE_STARTUP_TIMEOUT_KEY].get())
            request = float(self._vars[OPENCODE_REQUEST_TIMEOUT_KEY].get())
            max_context = int(self._vars[OPENCODE_MAX_CONTEXT_CHARS_KEY].get())
            if (
                startup <= 0
                or request <= 0
                or not 10_000 <= max_context <= 500_000
            ):
                raise ValueError
        except ValueError:
            show_error(
                self, "Некорректные настройки",
                "Timeout должен быть положительным, max context — от 10000 до 500000.",
            )
            return
        provider = self._vars[OPENCODE_PROVIDER_ID_KEY].get().strip()
        model = self._vars[OPENCODE_MODEL_ID_KEY].get().strip()
        if bool(provider) != bool(model):
            show_error(self, "Некорректные настройки", "Provider ID и Model ID задаются вместе.")
            return
        self.app.env_manager.save({key: var.get().strip() for key, var in self._vars.items()})
        self.app.opencode_manager.startup_timeout = startup
        self.app.opencode_manager.request_timeout = request
        client = self.app.opencode_manager.client
        if client is not None:
            client.timeout = request
        show_info(self, "OpenCode", "Настройки сохранены и будут использованы новым запросом.")

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self and self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
