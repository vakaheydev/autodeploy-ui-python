from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Mapping


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        result[key.strip()] = value
    return result


def update_env(path: Path, values: Mapping[str, str]) -> None:
    current = read_env(path)
    for key, value in values.items():
        clean_key = str(key).strip()
        if not clean_key or not clean_key.replace("_", "").isalnum():
            raise ValueError(f"Некорректное имя настройки: {key!r}")
        current[clean_key] = str(value).replace("\r", "").replace("\n", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(f"{key}={value}\n" for key, value in current.items()),
        encoding="utf-8",
    )
    try:
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(temporary, path)
