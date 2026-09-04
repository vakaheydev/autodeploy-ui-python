"""Безопасное локальное хранилище настроек в ``.env``.

Desktop-версия по-прежнему использует ``<project>/.env``. Web launcher задаёт
``AUTODEPLOY_ENV_FILE`` и хранит файл вне каталогов устанавливаемых версий.
"""
import os
import re
import stat
import threading
from pathlib import Path
from typing import Dict, Optional

ENV_FILE = Path(__file__).parent.parent / ".env"
ENV_FILE_OVERRIDE = "AUTODEPLOY_ENV_FILE"
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvManager:
    """
    Отвечает ТОЛЬКО за чтение и запись .env файла.
    Формат: KEY=VALUE (одна пара на строку, # — комментарий).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        configured = path or (
            Path(os.environ[ENV_FILE_OVERRIDE])
            if os.environ.get(ENV_FILE_OVERRIDE)
            else ENV_FILE
        )
        self._path = Path(configured).expanduser().resolve()
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, str]:
        """Загружает все переменные из .env и возвращает словарь."""
        result: Dict[str, str] = {}
        with self._lock:
            if not self._path.exists():
                return result
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    clean_value = value.strip()
                    if (
                        len(clean_value) >= 2
                        and clean_value[0] == clean_value[-1]
                        and clean_value[0] in {'"', "'"}
                    ):
                        clean_value = clean_value[1:-1]
                    result[key.strip()] = clean_value
        return result

    def save(self, values: Dict[str, str]) -> None:
        """
        Сохраняет переданные пары в .env файл.
        Существующие ключи обновляются, новые — добавляются.
        """
        with self._lock:
            existing = self.load()
            updates: Dict[str, str] = {}
            for key, value in values.items():
                clean_key = str(key).strip()
                if not _ENV_KEY_RE.fullmatch(clean_key):
                    raise ValueError(f"Некорректное имя настройки: {key!r}")
                updates[clean_key] = str(value)
            existing.update(updates)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as fh:
                for key, value in existing.items():
                    # Однострочный .env не должен позволять внедрять новые ключи.
                    safe = value.replace("\r", "").replace("\n", "")
                    fh.write(f"{key}={safe}\n")
            try:
                temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temporary, self._path)

    def get(self, key: str, default: str = "") -> str:
        """Возвращает значение одной переменной или default."""
        return self.load().get(key, default)
