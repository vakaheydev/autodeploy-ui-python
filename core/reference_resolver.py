"""
ReferenceResolver — цепочка ответственности для загрузки справочных данных.
Делегирует загрузку первому подходящему обработчику.
"""
from typing import Any, Dict, List, Optional

from forms.fields import ReferenceConfig
from handlers.base_reference_handler import BaseReferenceHandler


class ReferenceResolver:
    """
    Принимает список зарегистрированных обработчиков справочников
    и находит подходящий по конфигурации поля.

    Порядок обработчиков в списке определяет приоритет.
    """

    def __init__(self, handlers: List[BaseReferenceHandler]) -> None:
        self._handlers = handlers

    def resolve(
        self,
        config: ReferenceConfig,
        environment: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Загружает данные справочника.

        extra_params — дополнительные параметры для зависимых справочников
          (напр. {"api_id": "abc"}). Для HTTP подставляются в URL-шаблон.

        Raises:
            ValueError: если ни один обработчик не поддерживает source из config.
        """
        for handler in self._handlers:
            if handler.supports(config):
                return handler.load(config, environment, extra_params)
        raise ValueError(
            f"Нет обработчика для справочника с source='{config.source}'"
        )

    def add_handler(self, handler: BaseReferenceHandler) -> None:
        """Добавляет обработчик в конец цепочки."""
        self._handlers.append(handler)
