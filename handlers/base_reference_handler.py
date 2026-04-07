"""
BaseReferenceHandler — абстрактный обработчик справочников.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from forms.fields import ReferenceConfig


class BaseReferenceHandler(ABC):
    """
    Интерфейс обработчика справочных данных.
    Каждый обработчик знает, какие источники (source) он умеет обслуживать.
    """

    @abstractmethod
    def supports(self, config: ReferenceConfig) -> bool:
        """Возвращает True, если этот обработчик может загрузить данный справочник."""
        ...

    @abstractmethod
    def load(
        self, config: ReferenceConfig, environment: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Загружает и возвращает список элементов справочника.
        Каждый элемент — словарь с минимум двумя ключами:
          config.value_key (ID) и config.label_key (отображаемое имя).

        При ошибке следует вернуть пустой список и залогировать проблему,
        чтобы не ломать UI.
        """
        ...
