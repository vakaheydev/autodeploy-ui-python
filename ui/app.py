"""
Application — корень приложения.

Создаёт и связывает все сервисы, управляет навигацией между экранами.
"""
import tkinter as tk
from typing import List, Type

from config.environments import ENVIRONMENTS
from core.env_manager import EnvManager
from core.http_client import HttpClient
from core.reference_resolver import ReferenceResolver
from forms.loader import register_all_forms
from handlers.http_reference_handler import HttpReferenceHandler
from handlers.local_reference_handler import LocalReferenceHandler
from services.submit_service import SubmitService
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
        self._root.title("AutoDeploy UI")
        self._root.minsize(660, 480)
        self._root.resizable(True, True)

        # --- Тема (до создания любых виджетов) ---
        from ui.theme import apply as apply_theme, C
        apply_theme(self._root)
        self._root.configure(bg=C["bg"])

        # --- Сервисы ---
        self.env_manager = EnvManager()
        self.http_client = HttpClient(timeout=30)

        self.reference_resolver = ReferenceResolver(
            handlers=[
                LocalReferenceHandler(),
                HttpReferenceHandler(self.http_client),
            ]
        )
        self.submit_service = SubmitService(self.http_client, self.env_manager)

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

    def _get_main_screen_class(self) -> Type[BaseScreen]:
        from ui.screens.main_screen import MainScreen
        return MainScreen
