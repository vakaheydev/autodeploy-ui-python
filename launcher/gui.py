from __future__ import annotations

import queue
import threading
from pathlib import Path

from launcher.envfile import read_env, update_env
from launcher.paths import InstallPaths
from launcher.corporate_update import UPDATE_MANIFEST_URL


def run_launcher_gui(paths: InstallPaths, initial_bundle: Path | None = None) -> bool:
    """Show the dependency-free launcher. Returns True when Start was chosen."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    from launcher.installer import ReleaseInstaller
    from launcher.runtime import LauncherRuntime

    paths.ensure()
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    root = tk.Tk()
    root.title("Gravitee AutoDeploy")
    root.geometry("650x440")
    root.minsize(580, 410)
    root.configure(background="#f5f7fb")
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("TFrame", background="#f5f7fb")
    style.configure("Card.TFrame", background="#ffffff")
    style.configure("TLabel", background="#f5f7fb", foreground="#18243a", font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 22), foreground="#14213d")
    style.configure("Sub.TLabel", foreground="#64748b")
    style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(16, 10))
    style.configure("TButton", padding=(13, 9))
    content = ttk.Frame(root, padding=28)
    content.pack(fill="both", expand=True)
    ttk.Label(content, text="Gravitee AutoDeploy", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        content,
        text="Безопасная установка, обновление и запуск локального web-приложения",
        style="Sub.TLabel",
    ).pack(anchor="w", pady=(4, 22))
    card = ttk.Frame(content, style="Card.TFrame", padding=22)
    card.pack(fill="x")
    ttk.Label(card, text="TFS token", background="#ffffff", font=("Segoe UI Semibold", 10)).pack(anchor="w")
    ttk.Label(
        card,
        text="Единственная настройка launcher. Остальные server secrets остаются в config/.env.",
        background="#ffffff",
        foreground="#64748b",
    ).pack(anchor="w", pady=(3, 8))
    token = tk.StringVar(value=read_env(paths.env_file).get("TFS_TOKEN", ""))
    token_entry = ttk.Entry(card, textvariable=token, show="•", font=("Consolas", 10))
    token_entry.pack(fill="x", ipady=7)
    status = tk.StringVar(value="Готово")
    version = tk.StringVar(value="")
    ttk.Label(content, textvariable=status).pack(anchor="w", pady=(20, 3))
    ttk.Label(content, textvariable=version, style="Sub.TLabel").pack(anchor="w")
    progress = ttk.Progressbar(content, mode="indeterminate")
    progress.pack(fill="x", pady=(9, 18))
    buttons = ttk.Frame(content)
    buttons.pack(fill="x")
    start_requested = {"value": False}
    controls: list[ttk.Button] = []

    def save() -> None:
        update_env(paths.env_file, {"TFS_TOKEN": token.get().strip()})
        status.set("TFS token сохранён локально")

    def set_busy(value: bool) -> None:
        for button in controls:
            button.configure(state="disabled" if value else "normal")
        if value:
            progress.start(10)
        else:
            progress.stop()

    def worker(operation) -> None:  # noqa: ANN001
        set_busy(True)
        save()
        threading.Thread(target=operation, daemon=True).start()

    def install_initial() -> None:
        try:
            installed = ReleaseInstaller(paths, on_status=lambda text: events.put(("status", text))).install_bundle(initial_bundle)  # type: ignore[arg-type]
            events.put(("complete", f"Версия {installed} установлена"))
        except Exception as exc:
            events.put(("error", exc))

    def check_update() -> None:
        try:
            runtime = LauncherRuntime(paths, on_status=lambda text: events.put(("status", text)))
            check = runtime.check_update()
            events.put(("check", (runtime, check)))
        except Exception as exc:
            events.put(("error", exc))

    def install_update(runtime, check) -> None:  # noqa: ANN001
        try:
            installed = runtime.install_update(check)
            events.put(("complete", f"Версия {installed} установлена"))
        except Exception as exc:
            events.put(("error", exc))

    def start() -> None:
        save()
        try:
            if not ReleaseInstaller(paths).state().current:
                messagebox.showwarning("Gravitee AutoDeploy", "Сначала установите приложение")
                return
        except Exception as exc:
            messagebox.showerror("Gravitee AutoDeploy", str(exc))
            return
        start_requested["value"] = True
        root.destroy()

    def poll() -> None:
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "status":
                    status.set(str(payload))
                elif kind == "complete":
                    set_busy(False); status.set(str(payload)); refresh_version()
                elif kind == "error":
                    set_busy(False); status.set("Операция завершилась ошибкой")
                    messagebox.showerror("Gravitee AutoDeploy", str(payload))
                elif kind == "check":
                    runtime, check = payload  # type: ignore[misc]
                    set_busy(False)
                    if not check.update_available:
                        status.set(f"Версия {check.current_version} актуальна")
                    elif messagebox.askyesno(
                        f"Доступна версия {check.manifest.version}",
                        f"{check.manifest.changelog}\n\nУстановить обновление?",
                    ):
                        worker(lambda: install_update(runtime, check))
        except queue.Empty:
            pass
        if root.winfo_exists():
            root.after(100, poll)

    def refresh_version() -> None:
        try:
            state = ReleaseInstaller(paths).state()
            version.set(
                f"Текущая версия: {state.current or 'не установлена'}  ·  {paths.root}"
            )
        except Exception as exc:
            version.set(str(exc))

    save_button = ttk.Button(buttons, text="Сохранить token", command=save)
    save_button.pack(side="left")
    update_button = ttk.Button(buttons, text="Проверить обновления", command=lambda: worker(check_update))
    update_button.pack(side="left", padx=8)
    controls.extend((save_button, update_button))
    if initial_bundle is not None:
        install_button = ttk.Button(buttons, text="Установить пакет", style="Accent.TButton", command=lambda: worker(install_initial))
        install_button.pack(side="right", padx=(8, 0))
        controls.append(install_button)
    start_button = ttk.Button(buttons, text="Запустить", style="Accent.TButton", command=start)
    start_button.pack(side="right")
    controls.append(start_button)
    refresh_version()
    root.after(100, poll)
    configured = read_env(paths.env_file)
    if initial_bundle is None and (
        configured.get("AUTODEPLOY_UPDATE_MANIFEST_URL")
        or configured.get("AUTODEPLOY_UPDATE_PROVIDER")
        or UPDATE_MANIFEST_URL
    ):
        root.after(350, lambda: worker(check_update))
    token_entry.focus_set()
    root.mainloop()
    return bool(start_requested["value"])
