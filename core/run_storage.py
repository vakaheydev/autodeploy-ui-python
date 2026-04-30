"""
RunStorage — хранит историю отправленных форм.

Каждая запись содержит данные формы и снимок структуры (ключи + типы полей).
При восстановлении снимок сравнивается с текущей формой — если структура
изменилась, запись помечается устаревшей и не может быть восстановлена.
"""
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

_RUNS_FILE = Path(__file__).parent.parent / "data" / "runs.json"
_MAX_RUNS = 100


@dataclass
class RunRecord:
    run_id:          str
    form_id:         str
    environment:     str
    timestamp:       float
    form_data:       Dict[str, Any]
    fields_snapshot: Dict[str, str]   # {field_key: field_type_value}


class RunStorage:

    def __init__(self) -> None:
        _RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)

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
        runs = self._load_raw()
        runs.insert(0, asdict(record))
        _RUNS_FILE.write_text(
            json.dumps(runs[:_MAX_RUNS], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_all(self) -> List[RunRecord]:
        result = []
        for raw in self._load_raw():
            try:
                result.append(RunRecord(**raw))
            except Exception:
                pass
        return result

    def delete(self, run_id: str) -> None:
        runs = [r for r in self._load_raw() if r.get("run_id") != run_id]
        _RUNS_FILE.write_text(
            json.dumps(runs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_raw(self) -> List[Dict[str, Any]]:
        if not _RUNS_FILE.exists():
            return []
        try:
            return json.loads(_RUNS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
