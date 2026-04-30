"""
MainScreen — главный экран приложения.
"""
import tkinter as tk
from tkinter import ttk
from typing import List, Tuple

import ui.theme as theme
from config.environments import GRAVITEE_REPO_PATH_KEY
from ui.screens.base_screen import BaseScreen

# Уровень 1: группа окружения
_TIER1: List[Tuple[str, str]] = [
    ("test",    "Test"),
    ("regress", "Regress"),
    ("prod",    "Prod"),
]

# Уровень 2: тип сети
_TIER2: List[Tuple[str, str]] = [
    ("int", "Internal"),
    ("ext", "External"),
]


class MainScreen(BaseScreen):

    def _build(self) -> None:
        # --- Панель ветки (bottom-anchored — добавляется ДО top-элементов) ---
        branch_bar = tk.Frame(self, bg=theme.C["bg"])
        branch_bar.pack(side=tk.BOTTOM, anchor=tk.W, fill=tk.X, pady=(8, 0))

        self._branch_var = tk.StringVar(value=self._get_branch_name())

        tk.Label(
            branch_bar,
            textvariable=self._branch_var,
            font=theme.F["small"],
            bg=theme.C["bg"],
            fg=theme.C["text_muted"],
        ).pack(side=tk.LEFT)

        tk.Button(
            branch_bar,
            text="↻",
            font=theme.F["body"],
            bg=theme.C["bg"],
            fg=theme.C["text_muted"],
            activebackground=theme.C["ghost_h"],
            activeforeground=theme.C["text"],
            relief="flat", bd=0, cursor="hand2",
            command=self._refresh_branch,
        ).pack(side=tk.LEFT, padx=(4, 0))

        self._add_back_button()

        # --- Заголовок ---
        header = tk.Frame(self, bg=theme.C["bg"])
        header.pack(fill=tk.X, pady=(0, 14))

        tk.Label(
            header, text="🚀  AutoDeploy UI",
            font=theme.F["h1"], bg=theme.C["bg"], fg=theme.C["text"],
        ).pack(side=tk.LEFT)

        theme.separator(self, pady=0)

        # --- Двухуровневый выбор окружения ---
        env_card = theme.card(self, pady=12)

        tk.Label(
            env_card, text="ОКРУЖЕНИЕ",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 8))

        # Внутренние переменные состояния (независимы от app.current_environment)
        current = self.app.current_environment.get()  # напр. "test_int"
        parts = current.split("_", 1)
        self._t1 = tk.StringVar(value=parts[0] if parts else "test")
        self._t2 = tk.StringVar(value=parts[1] if len(parts) > 1 else "int")

        # Уровень 1: Test / Regress / Prod
        tk.Label(
            env_card, text="Среда",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(0, 4))

        self._seg1_btns: List[tk.Button] = []
        seg1 = tk.Frame(env_card, bg=theme.C["border"])
        seg1.pack(anchor=tk.W, padx=14, pady=(0, 12))

        for key, label in _TIER1:
            btn = self._seg_btn(seg1, label)
            btn.config(command=lambda k=key: self._select_t1(k))
            btn.pack(side=tk.LEFT)
            self._seg1_btns.append(btn)

        # Уровень 2: Internal / External
        tk.Label(
            env_card, text="Тип сети",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(0, 4))

        self._seg2_btns: List[tk.Button] = []
        seg2 = tk.Frame(env_card, bg=theme.C["border"])
        seg2.pack(anchor=tk.W, padx=14, pady=(0, 12))

        for key, label in _TIER2:
            btn = self._seg_btn(seg2, label)
            btn.config(command=lambda k=key: self._select_t2(k))
            btn.pack(side=tk.LEFT)
            self._seg2_btns.append(btn)

        # Применяем начальное выделение
        self._refresh_segments()

        theme.separator(self, pady=10)

        # --- Основная кнопка ---
        ttk.Button(
            self,
            text="  Выбрать форму  →",
            style="Primary.TButton",
            command=self._open_category,
        ).pack(pady=(0, 6))

        ttk.Button(
            self,
            text="🕑  Предыдущие запуски",
            style="Ghost.TButton",
            command=self._open_runs,
        ).pack(pady=(0, 6))

        # --- Статус ---
        self._status_var = tk.StringVar(value=self._status_text())
        ttk.Label(self, textvariable=self._status_var, style="Muted.TLabel").pack(pady=(6, 0))

    # ------------------------------------------------------------------
    # Сегментированные кнопки
    # ------------------------------------------------------------------

    @staticmethod
    def _seg_btn(parent: tk.Frame, label: str) -> tk.Button:
        """Создаёт одну кнопку сегментированного контрола."""
        return tk.Button(
            parent, text=label,
            font=theme.F["body"],
            relief="flat", bd=0,
            padx=18, pady=7,
            cursor="hand2",
            activebackground=theme.C["primary_h"],
            activeforeground=theme.C["primary_fg"],
        )

    def _refresh_segments(self) -> None:
        """Перекрашивает кнопки в соответствии с текущим выбором."""
        t1 = self._t1.get()
        t2 = self._t2.get()

        for (key, _), btn in zip(_TIER1, self._seg1_btns):
            selected = key == t1
            btn.config(
                bg=theme.C["primary"] if selected else theme.C["surface"],
                fg=theme.C["primary_fg"] if selected else theme.C["text"],
            )

        for (key, _), btn in zip(_TIER2, self._seg2_btns):
            selected = key == t2
            btn.config(
                bg=theme.C["primary"] if selected else theme.C["surface"],
                fg=theme.C["primary_fg"] if selected else theme.C["text"],
            )

    def _select_t1(self, key: str) -> None:
        self._t1.set(key)
        self._commit()

    def _select_t2(self, key: str) -> None:
        self._t2.set(key)
        self._commit()

    def _commit(self) -> None:
        """Объединяет tier1+tier2 → current_environment."""
        env_key = f"{self._t1.get()}_{self._t2.get()}"
        self.app.current_environment.set(env_key)
        self._refresh_segments()
        self._status_var.set(self._status_text())
        self._on_environment_changed(env_key)

    # ------------------------------------------------------------------

    def _status_text(self) -> str:
        env_key = self.app.current_environment.get()
        from config.environments import ENVIRONMENT_MAP
        env = ENVIRONMENT_MAP.get(env_key)
        return f"Активное окружение: {env.label if env else env_key}"

    def _open_category(self) -> None:
        from ui.screens.category_screen import CategoryScreen
        self.app.navigate_to(CategoryScreen)

    def _open_runs(self) -> None:
        from ui.screens.runs_screen import RunsScreen
        self.app.navigate_to(RunsScreen)

    # ------------------------------------------------------------------
    # Переопределяемые хуки
    # ------------------------------------------------------------------

    def _on_environment_changed(self, env_key: str) -> None:
        """Вызывается при каждом переключении окружения. Переопределить при необходимости."""

    def _get_branch_name(self) -> str:
        """
        Возвращает название текущей ветки для отображения внизу экрана.
        Путь к репозиторию берётся из env_manager по ключу GRAVITEE_REPO_PATH_KEY.
        """
        env = self.app.env_manager.load()
        _ = env.get(GRAVITEE_REPO_PATH_KEY, "")
        return ""

    def _refresh_branch(self) -> None:
        """Вызывается при нажатии ↻ рядом с веткой. Обновляет отображаемое название."""
        self._branch_var.set(self._get_branch_name())
