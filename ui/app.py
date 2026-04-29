"""
Application — корень приложения.

Создаёт и связывает все сервисы, управляет навигацией между экранами.
"""
import tkinter as tk
from typing import List, Type

from config.environments import ENVIRONMENTS
from core.env_manager import EnvManager
from core.http_client import HttpClient
from core.reference_cache import ReferenceCache
from core.reference_resolver import ReferenceResolver
from forms.loader import register_all_forms
from handlers.http_reference_handler import HttpReferenceHandler
from handlers.local_reference_handler import LocalReferenceHandler
from services.gravitee_service import GraviteeService
from services.itsm_service import ITSMService
from services.submit_service import SubmitService
from services.tfs_service import TfsService
from ui.screens.base_screen import BaseScreen


class Application:
    """
    Точка сборки приложения (Composition Root).

    Создаёт все сервисы один раз и передаёт их экранам через self.
    Управляет стеком навигации.
    """

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._root = tk.Tk()
        self._root.title("Gravitee Admin UI")
        self._root.minsize(660, 480)
        self._root.resizable(True, True)

        # --- Тема (до создания любых виджетов) ---
        from ui.theme import apply as apply_theme, C
        apply_theme(self._root)
        self._root.configure(bg=C["bg"])

        # --- Сервисы ---
        self.env_manager = EnvManager()
        self.http_client = HttpClient(timeout=30)
        self.reference_cache = ReferenceCache()

        self.reference_resolver = ReferenceResolver(
            handlers=[
                LocalReferenceHandler(),
                HttpReferenceHandler(self.http_client, self.reference_cache, self.env_manager),
            ]
        )
        self.submit_service    = SubmitService(self.http_client, self.env_manager)
        self.tfs_service       = TfsService(self.env_manager, self.http_client)
        self.itsm_service      = ITSMService(self.env_manager, self.http_client)
        self.gravitee_service  = GraviteeService(self.env_manager, self.http_client)

        # --- Состояние приложения ---
        default_env = ENVIRONMENTS[0].key
        self.current_environment = tk.StringVar(value=default_env)

        # --- Регистрация форм ---
        register_all_forms()

        # --- Навигация ---
        self._screen_stack: List[Type[BaseScreen]] = []
        self._current_screen: BaseScreen | None = None
        from ui.theme import C
        self._main_container = tk.Frame(self._root, bg=C["bg"])
        self._main_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        # --- Глобальные биндинги ---
        self._root.bind_all("<Control-KeyPress>", self._on_ctrl_key)
        self._root.bind_all("<Control-BackSpace>", self._on_ctrl_backspace)

        # --- Запуск ---
        self.navigate_to(self._get_main_screen_class())

    # ------------------------------------------------------------------
    # Навигация
    # ------------------------------------------------------------------

    def navigate_to(self, screen_class: Type[BaseScreen], **kwargs) -> None:
        """
        Переходит на новый экран. Предыдущий уничтожается.
        Текущий класс добавляется в стек для возможности go_back().
        """
        if self._current_screen is not None:
            # Сохраняем класс и kwargs для возможного возврата
            self._screen_stack.append(
                (type(self._current_screen), self._current_kwargs)
            )
            self._current_screen.destroy()

        self._current_kwargs = kwargs
        self._current_screen = screen_class(
            self._main_container, app=self, **kwargs
        )
        self._current_screen.pack(fill=tk.BOTH, expand=True)

    def go_back(self) -> None:
        """Возвращается на предыдущий экран из стека."""
        if not self._screen_stack:
            return
        screen_class, kwargs = self._screen_stack.pop()
        if self._current_screen is not None:
            self._current_screen.destroy()
        self._current_kwargs = kwargs
        self._current_screen = screen_class(
            self._main_container, app=self, **kwargs
        )
        self._current_screen.pack(fill=tk.BOTH, expand=True)

    def go_home(self) -> None:
        """Возвращается на главный экран, очищая стек."""
        self._screen_stack.clear()
        if self._current_screen is not None:
            self._current_screen.destroy()
        self._current_kwargs = {}
        main_class = self._get_main_screen_class()
        self._current_screen = main_class(self._main_container, app=self)
        self._current_screen.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._root.mainloop()

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _on_ctrl_key(self, event: tk.Event) -> None:
        """
        Фикс Ctrl+A/C/V/X на русской раскладке + Ctrl+Backspace (удалить слово).
        Keysym зависит от раскладки, keycode — физический и не зависит.
        65=A, 67=C, 86=V, 88=X, 8=Backspace.
        """
        w = event.widget
        if event.keycode == 65:           # Ctrl+A — выделить всё
            if isinstance(w, tk.Entry):
                w.select_range(0, tk.END)
                w.icursor(tk.END)
            elif isinstance(w, tk.Text):
                w.tag_add(tk.SEL, "1.0", tk.END)
                w.mark_set(tk.INSERT, tk.END)

        elif event.keycode == 67 and event.keysym.lower() != 'c':   # Ctrl+C, русская раскладка
            if isinstance(w, tk.Entry):
                if w.selection_present():
                    self._root.clipboard_clear()
                    self._root.clipboard_append(w.selection_get())
            elif isinstance(w, tk.Text):
                try:
                    self._root.clipboard_clear()
                    self._root.clipboard_append(w.get(tk.SEL_FIRST, tk.SEL_LAST))
                except tk.TclError:
                    pass

        elif event.keycode == 88 and event.keysym.lower() != 'x':   # Ctrl+X, русская раскладка
            if isinstance(w, tk.Entry):
                if w.selection_present():
                    self._root.clipboard_clear()
                    self._root.clipboard_append(w.selection_get())
                    w.delete(tk.SEL_FIRST, tk.SEL_LAST)
            elif isinstance(w, tk.Text):
                try:
                    self._root.clipboard_clear()
                    self._root.clipboard_append(w.get(tk.SEL_FIRST, tk.SEL_LAST))
                    w.delete(tk.SEL_FIRST, tk.SEL_LAST)
                except tk.TclError:
                    pass

        elif event.keycode == 86 and event.keysym.lower() != 'v':   # Ctrl+V, русская раскладка
            if isinstance(w, tk.Entry):
                try:
                    text = self._root.clipboard_get()
                    if w.selection_present():
                        w.delete(tk.SEL_FIRST, tk.SEL_LAST)
                    w.insert(tk.INSERT, text)
                except tk.TclError:
                    pass
            elif isinstance(w, tk.Text):
                try:
                    text = self._root.clipboard_get()
                    try:
                        w.delete(tk.SEL_FIRST, tk.SEL_LAST)
                    except tk.TclError:
                        pass
                    w.insert(tk.INSERT, text)
                except tk.TclError:
                    pass

    def _on_ctrl_backspace(self, event: tk.Event) -> str:
        """Ctrl+Backspace — удалить предыдущее слово (как в текстовых редакторах)."""
        w = event.widget
        if isinstance(w, tk.Entry):
            pos = w.index(tk.INSERT)
            text = w.get()
            i = pos - 1
            while i >= 0 and text[i] in (' ', '\t'):
                i -= 1
            while i >= 0 and text[i] not in (' ', '\t'):
                i -= 1
            w.delete(i + 1, pos)
            return "break"
        elif isinstance(w, tk.Text):
            w.delete("insert -1c wordstart", "insert")
            return "break"

    def _get_main_screen_class(self) -> Type[BaseScreen]:
        from ui.screens.home_screen import HomeScreen
        return HomeScreen
