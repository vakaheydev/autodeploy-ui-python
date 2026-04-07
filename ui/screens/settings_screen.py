"""
SettingsScreen — экран настроек (токены).
"""
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict

import ui.theme as theme
from config.environments import ENVIRONMENTS, TFS_TOKEN_KEY, gravitee_token_key
from ui.screens.base_screen import BaseScreen


class SettingsScreen(BaseScreen):

    def _build(self) -> None:
        self._add_back_button()
        self._add_title("Настройки")

        saved = self.app.env_manager.load()
        self._token_vars: Dict[str, tk.StringVar] = {}

        # --- Gravitee ---
        grav_card = theme.card(self, pady=0)
        tk.Label(
            grav_card, text="GRAVITEE TOKENS  (по окружениям)",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 6))

        grid = tk.Frame(grav_card, bg=theme.C["surface"])
        grid.pack(fill=tk.X, padx=14, pady=(0, 10))

        for i, env in enumerate(ENVIRONMENTS):
            env_key = gravitee_token_key(env.key)
            var = tk.StringVar(value=saved.get(env_key, ""))
            self._token_vars[env_key] = var

            tk.Label(
                grid, text=env.label,
                font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_label"],
                width=18, anchor="w",
            ).grid(row=i, column=0, sticky="w", pady=3)

            entry = self._make_entry(grid, var)
            entry.grid(row=i, column=1, sticky="ew", pady=3, padx=(6, 0))

            show_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                grid,
                text="показать",
                variable=show_var,
                style="TCheckbutton",
                command=lambda e=entry, v=show_var: e.config(show="" if v.get() else "*"),
            ).grid(row=i, column=2, padx=8)

        grid.columnconfigure(1, weight=1)

        theme.separator(self, pady=10)

        # --- TFS ---
        tfs_card = theme.card(self, pady=0)
        tk.Label(
            tfs_card, text="TFS / Azure DevOps",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 6))

        tfs_row = tk.Frame(tfs_card, bg=theme.C["surface"])
        tfs_row.pack(fill=tk.X, padx=14, pady=(0, 10))

        tfs_var = tk.StringVar(value=saved.get(TFS_TOKEN_KEY, ""))
        self._token_vars[TFS_TOKEN_KEY] = tfs_var

        tk.Label(
            tfs_row, text="TFS_TOKEN",
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_label"],
            width=18, anchor="w",
        ).pack(side=tk.LEFT)

        tfs_entry = self._make_entry(tfs_row, tfs_var)
        tfs_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        tfs_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tfs_row,
            text="показать",
            variable=tfs_show,
            style="TCheckbutton",
            command=lambda e=tfs_entry, v=tfs_show: e.config(show="" if v.get() else "*"),
        ).pack(side=tk.LEFT, padx=8)

        # --- Сохранить ---
        theme.separator(self, pady=10)
        ttk.Button(
            self, text="Сохранить", style="Primary.TButton", command=self._save,
        ).pack(anchor=tk.W)

    # ------------------------------------------------------------------

    def _make_entry(self, parent: tk.Widget, var: tk.StringVar) -> tk.Entry:
        entry = tk.Entry(
            parent, textvariable=var, show="*",
            bg=theme.C["input_bg"], fg=theme.C["text"],
            relief="solid", bd=1,
            font=theme.F["body"],
            insertbackground=theme.C["text"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )
        return entry

    def _save(self) -> None:
        values = {key: var.get() for key, var in self._token_vars.items()}
        try:
            self.app.env_manager.save(values)
            messagebox.showinfo("Настройки", "Токены сохранены.")
            self.app.go_back()
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{exc}")
