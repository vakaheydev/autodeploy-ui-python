"""
LocalReferenceHandler — загрузка справочников из локальных JSON файлов.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from forms.fields import ReferenceConfig
from handlers.base_reference_handler import BaseReferenceHandler

# Директория с локальными справочниками
REFERENCES_DIR = Path(__file__).parent.parent / "config" / "references"
_log = logging.getLogger(__name__)


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
        self,
        config: ReferenceConfig,
        environment: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        file_path = REFERENCES_DIR / config.resource
        if not file_path.exists():
            _log.warning("Reference file not found resource=%s", config.resource)
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning(
                "Reference file read failed resource=%s error_type=%s",
                config.resource,
                type(exc).__name__,
            )
            return []

        items = data if isinstance(data, list) else data.get("items", [])
        return self._validate_items(items, config)

    # ------------------------------------------------------------------

    def _validate_items(
        self, items: list, config: ReferenceConfig
    ) -> List[Dict[str, Any]]:
        """Отфильтровывает объекты, у которых нет нужных ключей."""
        valid = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if config.value_key not in item or config.label_key not in item:
                _log.warning(
                    "Reference item skipped resource=%s index=%d missing_keys=%s,%s",
                    config.resource,
                    index,
                    config.value_key,
                    config.label_key,
                )
                continue
            valid.append(item)
        return valid
