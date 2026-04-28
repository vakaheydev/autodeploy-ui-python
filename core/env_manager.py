"""
EnvManager — чтение и запись токенов из .env файла.
Не требует сторонних библиотек.
"""
from pathlib import Path
from typing import Dict

ENV_FILE = Path(__file__).parent.parent / ".env"


class EnvManager:
    """
    Отвечает ТОЛЬКО за чтение и запись .env файла.
    Формат: KEY=VALUE (одна пара на строку, # — комментарий).
    """

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, str]:
        """Загружает все переменные из .env и возвращает словарь."""
        result: Dict[str, str] = {}
        if not ENV_FILE.exists():
            return result
        with open(ENV_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
        return result

    def save(self, values: Dict[str, str]) -> None:
        """
        Сохраняет переданные пары в .env файл.
        Существующие ключи обновляются, новые — добавляются.
        """
        existing = self.load()
        existing.update(values)
        with open(ENV_FILE, "w", encoding="utf-8") as fh:
            for key, value in existing.items():
                fh.write(f"{key}={value}\n")

    def get(self, key: str, default: str = "") -> str:
        """Возвращает значение одной переменной или default."""
        return self.load().get(key, default)
