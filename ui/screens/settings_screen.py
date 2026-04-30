"""
SettingsScreen — экран настроек (токены).
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict

import ui.theme as theme
from config.environments import (
    CERT_PATH_KEY, ENVIRONMENTS, GRAVITEE_REPO_PATH_KEY, ITSM_LOGIN_KEY,
    ITSM_PASSWORD_KEY, TFS_TOKEN_KEY, gravitee_token_key,
)
from ui.screens.base_screen import BaseScreen


class SettingsScreen(BaseScreen):

    def _build(self) -> None:
        self._add_back_button()
        self._add_title("Настройки")

        saved = self.app.env_manager.load()
        self._token_vars: Dict[str, tk.StringVar] = {}

        # --- Прокручиваемый контейнер ---
        wrap = tk.Frame(self, bg=theme.C["bg"])
        wrap.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(wrap, bg=theme.C["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)

        sf = tk.Frame(canvas, bg=theme.C["bg"])
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _win = canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win, width=e.width - 2))
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        # --- Gravitee ---
        grav_card = theme.card(sf, pady=0)
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

        theme.separator(sf, pady=10)

        # --- Gravitee Repository ---
        repo_card = theme.card(sf, pady=0)
        tk.Label(
            repo_card, text="GRAVITEE REPOSITORY",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 6))

        repo_row = tk.Frame(repo_card, bg=theme.C["surface"])
        repo_row.pack(fill=tk.X, padx=14, pady=(0, 10))

        repo_var = tk.StringVar(value=saved.get(GRAVITEE_REPO_PATH_KEY, ""))
        self._token_vars[GRAVITEE_REPO_PATH_KEY] = repo_var

        tk.Label(
            repo_row, text="Repository path",
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_label"],
            width=18, anchor="w",
        ).pack(side=tk.LEFT)

        tk.Entry(
            repo_row, textvariable=repo_var,
            bg=theme.C["input_bg"], fg=theme.C["text"],
            relief="solid", bd=1,
            font=theme.F["body"],
            insertbackground=theme.C["text"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))

        def _browse_repo():
            path = filedialog.askdirectory(
                title="Выберите папку репозитория Gravitee",
                initialdir=repo_var.get() or "/",
            )
            if path:
                repo_var.set(path)

        tk.Button(
            repo_row, text="📁",
            font=theme.F["body"],
            bg=theme.C["surface"],
            fg=theme.C["text"],
            activebackground=theme.C["ghost_h"],
            activeforeground=theme.C["text"],
            relief="flat", bd=0, cursor="hand2",
            command=_browse_repo,
        ).pack(side=tk.LEFT)

        theme.separator(sf, pady=10)

        # --- Сертификат ---
        cert_card = theme.card(sf, pady=0)
        tk.Label(
            cert_card, text="СЕРТИФИКАТ",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 6))

        cert_row = tk.Frame(cert_card, bg=theme.C["surface"])
        cert_row.pack(fill=tk.X, padx=14, pady=(0, 10))

        cert_var = tk.StringVar(value=saved.get(CERT_PATH_KEY, ""))
        self._token_vars[CERT_PATH_KEY] = cert_var

        tk.Label(
            cert_row, text="Путь к сертификату",
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_label"],
            width=18, anchor="w",
        ).pack(side=tk.LEFT)

        tk.Entry(
            cert_row, textvariable=cert_var,
            bg=theme.C["input_bg"], fg=theme.C["text"],
            relief="solid", bd=1,
            font=theme.F["body"],
            insertbackground=theme.C["text"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))

        def _browse_cert():
            path = filedialog.askopenfilename(
                title="Выберите файл сертификата",
                initialdir=cert_var.get() or "/",
                filetypes=[("Certificate files", "*.pem *.crt *.cer *.p12 *.pfx"), ("All files", "*.*")],
            )
            if path:
                cert_var.set(path)

        tk.Button(
            cert_row, text="📁",
            font=theme.F["body"],
            bg=theme.C["surface"],
            fg=theme.C["text"],
            activebackground=theme.C["ghost_h"],
            activeforeground=theme.C["text"],
            relief="flat", bd=0, cursor="hand2",
            command=_browse_cert,
        ).pack(side=tk.LEFT)

        theme.separator(sf, pady=10)

        # --- TFS ---
        tfs_card = theme.card(sf, pady=0)
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

        theme.separator(sf, pady=10)

        # --- ITSM ---
        itsm_card = theme.card(sf, pady=0)
        tk.Label(
            itsm_card, text="ITSM",
            font=theme.F["small"], bg=theme.C["surface"], fg=theme.C["text_muted"],
        ).pack(anchor=tk.W, padx=14, pady=(10, 6))

        itsm_grid = tk.Frame(itsm_card, bg=theme.C["surface"])
        itsm_grid.pack(fill=tk.X, padx=14, pady=(0, 10))

        # Логин
        itsm_login_var = tk.StringVar(value=saved.get(ITSM_LOGIN_KEY, ""))
        self._token_vars[ITSM_LOGIN_KEY] = itsm_login_var

        tk.Label(
            itsm_grid, text="Логин",
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_label"],
            width=18, anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=3)

        login_entry = tk.Entry(
            itsm_grid, textvariable=itsm_login_var,
            bg=theme.C["input_bg"], fg=theme.C["text"],
            relief="solid", bd=1,
            font=theme.F["body"],
            insertbackground=theme.C["text"],
            highlightthickness=1,
            highlightbackground=theme.C["input_border"],
            highlightcolor=theme.C["border_focus"],
        )
        login_entry.grid(row=0, column=1, sticky="ew", pady=3, padx=(6, 0))
        # Пустой столбец для выравнивания с паролем
        tk.Label(itsm_grid, bg=theme.C["surface"], width=10).grid(row=0, column=2)

        # Пароль
        itsm_pass_var = tk.StringVar(value=saved.get(ITSM_PASSWORD_KEY, ""))
        self._token_vars[ITSM_PASSWORD_KEY] = itsm_pass_var

        tk.Label(
            itsm_grid, text="Пароль",
            font=theme.F["body"], bg=theme.C["surface"], fg=theme.C["text_label"],
            width=18, anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=3)

        pass_entry = self._make_entry(itsm_grid, itsm_pass_var)
        pass_entry.grid(row=1, column=1, sticky="ew", pady=3, padx=(6, 0))

        pass_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            itsm_grid,
            text="показать",
            variable=pass_show,
            style="TCheckbutton",
            command=lambda e=pass_entry, v=pass_show: e.config(show="" if v.get() else "*"),
        ).grid(row=1, column=2, padx=8)

        itsm_grid.columnconfigure(1, weight=1)

        # --- Сохранить ---
        theme.separator(sf, pady=10)
        ttk.Button(
            sf, text="Сохранить", style="Primary.TButton", command=self._save,
        ).pack(anchor=tk.W, pady=(0, 10))

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
            messagebox.showinfo("Настройки", "Настройки сохранены.")
            self.app.go_back()
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{exc}")
