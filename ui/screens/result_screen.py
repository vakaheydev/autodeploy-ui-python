"""
ResultScreen — экран результата после отправки формы.

Отображает ответ сервера и, если форма настроила опрос, периодически
обновляет содержимое GET-запросом к get_poll_endpoint().

Логика опроса:
  1. После показа начального ответа планируется _schedule_poll()
  2. _run_poll() запускает GET в фоновом потоке
  3. Результат возвращается в главный поток через after(0, ...)
  4. При уничтожении экрана опрос корректно останавливается
"""
import threading
import tkinter as tk
from datetime import datetime
from tkinter import scrolledtext, ttk
from typing import Any, Optional

import ui.theme as theme
from forms.base_form import BaseForm
from ui.screens.base_screen import BaseScreen


class ResultScreen(BaseScreen):

    def __init__(
        self,
        master: tk.Widget,
        app,
        form: BaseForm,
        environment: str,
        initial_response: Any,
        **kwargs,
    ) -> None:
        self._form = form
        self._environment = environment
        self._initial_response = initial_response
        self._poll_after_id: Optional[str] = None
        self._destroyed = False
        self._poll_running = False   # защита от параллельных запросов
        self._paused = False
        super().__init__(master, app, **kwargs)

    # ------------------------------------------------------------------
    # Построение экрана
    # ------------------------------------------------------------------

    def _build(self) -> None:
        cfg = self._form.get_result_config()
        self._cfg = cfg

        self._add_back_button()

        # Заголовок
        title_text = cfg.title if cfg.title else self._form.title
        header = tk.Frame(self, bg=theme.C["bg"])
        header.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            header, text=title_text,
            font=theme.F["h1"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(side=tk.LEFT)

        # Бейдж «автообновление»
        if cfg.poll_interval_ms:
            secs = cfg.poll_interval_ms // 1000
            theme.badge(
                header,
                f"↻ каждые {secs} с",
                theme.C["badge_api"],
            ).pack(side=tk.LEFT, padx=(10, 0), pady=(4, 0), anchor="s")

        # Строка «Последнее обновление»
        self._ts_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._ts_var, style="Muted.TLabel").pack(
            anchor=tk.W, pady=(0, 4)
        )

        theme.separator(self, pady=4)

        # Область контента
        self._content = scrolledtext.ScrolledText(
            self,
            wrap=tk.WORD,
            font=theme.F["mono"],
            bg=theme.C["surface"], fg=theme.C["text"],
            relief="flat", bd=0, padx=10, pady=8,
        )
        self._content.pack(fill=tk.BOTH, expand=True, padx=2)

        # Кнопки управления
        theme.separator(self, pady=6)
        self._footer = tk.Frame(self, bg=theme.C["bg"])
        self._footer.pack(fill=tk.X)

        if cfg.poll_interval_ms:
            self._pause_var = tk.StringVar(value="⏸ Пауза")
            self._paused = False
            self._pause_btn = ttk.Button(
                self._footer,
                textvariable=self._pause_var,
                style="Secondary.TButton",
                command=self._toggle_pause,
            )
            self._pause_btn.pack(side=tk.LEFT, padx=(0, 8))

            self._stop_btn = ttk.Button(
                self._footer,
                text="⏹ Стоп",
                style="Secondary.TButton",
                command=self._stop_poll,
            )
            self._stop_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            self._footer,
            text="На главную",
            style="Ghost.TButton",
            command=self.app.go_home,
        ).pack(side=tk.RIGHT)

        # Показать начальный контент и запустить опрос
        initial_content = self._form.build_result_content(
            self._environment, self._initial_response
        )
        self._set_content(initial_content)
        self._update_timestamp()

        if cfg.poll_interval_ms:
            self._schedule_poll()

    # ------------------------------------------------------------------
    # Опрос
    # ------------------------------------------------------------------

    def _schedule_poll(self) -> None:
        if self._destroyed or self._paused:
            return
        self._poll_after_id = self.after(self._cfg.poll_interval_ms, self._run_poll)

    def _run_poll(self) -> None:
        if self._destroyed or self._poll_running:
            return

        endpoint = self._form.get_poll_endpoint(self._environment, self._initial_response)
        if not endpoint:
            # Форма не вернула URL — просто планируем следующий цикл
            self._schedule_poll()
            return

        self._poll_running = True

        def _worker() -> None:
            try:
                self.app.submit_service.set_auth(self._form, self._environment)
                response = self.app.http_client.get(endpoint)
                error: Optional[str] = None
            except Exception as exc:
                response = None
                error = str(exc)

            if not self._destroyed:
                self.after(0, lambda: self._on_poll_result(response, error))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_poll_result(self, response: Any, error: Optional[str]) -> None:
        if self._destroyed:
            return

        self._poll_running = False

        if error:
            self._set_content(f"[Ошибка опроса]\n{error}")
        else:
            content = self._form.build_poll_content(self._environment, response)
            self._set_content(content)

        self._update_timestamp()
        self._schedule_poll()

    # ------------------------------------------------------------------
    # Пауза / возобновление
    # ------------------------------------------------------------------

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._paused:
            self._pause_var.set("▶ Возобновить")
            if self._poll_after_id:
                try:
                    self.after_cancel(self._poll_after_id)
                except Exception:
                    pass
                self._poll_after_id = None
        else:
            self._pause_var.set("⏸ Пауза")
            self._schedule_poll()

    def _stop_poll(self) -> None:
        """Безвозвратно останавливает опрос и убирает кнопки управления."""
        self._paused = True
        if self._poll_after_id:
            try:
                self.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None
        # Убираем кнопки паузы и стопа
        try:
            self._pause_btn.destroy()
            self._stop_btn.destroy()
        except Exception:
            pass
        self._ts_var.set("Опрос остановлен")

    # ------------------------------------------------------------------
    # Обновление UI
    # ------------------------------------------------------------------

    def _set_content(self, text: str) -> None:
        self._content.config(state=tk.NORMAL)
        self._content.delete("1.0", tk.END)
        self._content.insert("1.0", text)
        self._content.config(state=tk.DISABLED)

    def _update_timestamp(self) -> None:
        self._ts_var.set(f"Обновлено: {datetime.now().strftime('%H:%M:%S')}")

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    def destroy(self) -> None:
        self._destroyed = True
        if self._poll_after_id:
            try:
                self.after_cancel(self._poll_after_id)
            except Exception:
                pass
        super().destroy()
