"""
LocalReferenceHandler — загрузка справочников из локальных JSON файлов.
"""
import json
from pathlib import Path
from typing import Any, Dict, List

from forms.fields import ReferenceConfig
from handlers.base_reference_handler import BaseReferenceHandler

# Директория с локальными справочниками
REFERENCES_DIR = Path("config/references")


class LocalReferenceHandler(BaseReferenceHandler):
    """
    Читает справочные данные из JSON файлов в config/references/.

    Поддерживаемые форматы файла:
      - Список объектов: [{"id": "...", "name": "..."}, ...]
      - Объект с items: {"items": [...], ...}
    """

    def supports(self, config: ReferenceConfig) -> bool:
        return config.source == "local"

    def load(
        self, config: ReferenceConfig, environment: str = ""
    ) -> List[Dict[str, Any]]:
        file_path = REFERENCES_DIR / config.resource
        if not file_path.exists():
            print(f"[LocalReferenceHandler] Файл не найден: {file_path}")
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[LocalReferenceHandler] Ошибка чтения {file_path}: {exc}")
            return []

        items = data if isinstance(data, list) else data.get("items", [])
        return self._validate_items(items, config)

    # ------------------------------------------------------------------

    def _validate_items(
        self, items: list, config: ReferenceConfig
    ) -> List[Dict[str, Any]]:
        """Отфильтровывает объекты, у которых нет нужных ключей."""
        valid = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if config.value_key not in item or config.label_key not in item:
                print(
                    f"[LocalReferenceHandler] Пропущен элемент без ключей "
                    f"'{config.value_key}'/'{config.label_key}': {item}"
                )
                continue
            valid.append(item)
        return valid
