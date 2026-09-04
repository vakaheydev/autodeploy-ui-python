"""
RunStorage — хранит историю отправленных форм.

Каждая запись содержит данные формы и снимок структуры (ключи + типы полей).
При восстановлении снимок сравнивается с текущей формой — если структура
изменилась, запись помечается устаревшей и не может быть восстановлена.
"""
import json
import logging
import os
import stat
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

_RUNS_FILE = Path(__file__).parent.parent / "data" / "runs.json"
_MAX_RUNS = 100
_log = logging.getLogger(__name__)


@dataclass
class RunRecord:
    run_id:          str
    form_id:         str
    environment:     str
    timestamp:       float
    form_data:       Dict[str, Any]
    fields_snapshot: Dict[str, str]   # {field_key: field_type_value}


class RunStorage:

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path or _RUNS_FILE).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def save(
        self,
        form_id:         str,
        environment:     str,
        form_data:       Dict[str, Any],
        fields_snapshot: Dict[str, str],
    ) -> None:
        record = RunRecord(
            run_id=str(uuid.uuid4()),
            form_id=form_id,
            environment=environment,
            timestamp=time.time(),
            form_data=form_data,
            fields_snapshot=fields_snapshot,
        )
        with self._lock:
            runs = self._load_raw()
            runs.insert(0, asdict(record))
            self._write(runs[:_MAX_RUNS])

    def load_all(self) -> List[RunRecord]:
        with self._lock:
            result = []
            for raw in self._load_raw():
                try:
                    result.append(RunRecord(**raw))
                except Exception as exc:
                    _log.warning(
                        "Invalid run history record skipped error_type=%s",
                        type(exc).__name__,
                    )
            return result

    def delete(self, run_id: str) -> None:
        with self._lock:
            runs = [r for r in self._load_raw() if r.get("run_id") != run_id]
            self._write(runs)

    def _load_raw(self) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("run history root must be a list")
            return payload
        except Exception as exc:
            _log.warning(
                "Run history read failed file=%s error_type=%s",
                self._path.name,
                type(exc).__name__,
            )
            return []

    def _write(self, runs: List[Dict[str, Any]]) -> None:
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(runs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(temporary, self._path)
