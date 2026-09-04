from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+]([0-9A-Za-z.-]+))?$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def version_key(value: str) -> tuple[int, int, int, int, str]:
    match = _VERSION_RE.fullmatch(str(value).strip())
    if not match:
        raise ValueError(f"Некорректная версия {value!r}; ожидается SemVer X.Y.Z")
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    suffix = match.group(4) or ""
    return major, minor, patch, 1 if not suffix else 0, suffix


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    artifact_url: str
    sha256: str
    changelog: str
    size: int | None = None
    minimum_launcher_version: str = "1.0.0"
    schema_version: int = 1

    @classmethod
    def parse(cls, payload: bytes | str | dict[str, Any]) -> "ReleaseManifest":
        if isinstance(payload, bytes):
            if len(payload) > 2 * 1024 * 1024:
                raise ValueError("Manifest превышает 2 МБ")
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError("Manifest должен быть JSON-объектом")
        unknown = set(payload) - {
            "schema_version", "version", "artifact_url", "sha256", "size",
            "changelog", "minimum_launcher_version",
        }
        if unknown:
            raise ValueError("Неизвестные поля manifest: " + ", ".join(sorted(unknown)))
        version = str(payload.get("version", "")).strip()
        minimum = str(payload.get("minimum_launcher_version", "1.0.0")).strip()
        version_key(version)
        version_key(minimum)
        sha256 = str(payload.get("sha256", "")).strip().lower()
        if not _SHA_RE.fullmatch(sha256):
            raise ValueError("sha256 artifact должен содержать 64 hex-символа")
        url = str(payload.get("artifact_url", "")).strip()
        if not url:
            raise ValueError("artifact_url отсутствует")
        size_value = payload.get("size")
        size = int(size_value) if size_value is not None else None
        if size is not None and not 0 < size <= 1024 * 1024 * 1024:
            raise ValueError("Некорректный размер artifact")
        schema = int(payload.get("schema_version", 1))
        if schema != 1:
            raise ValueError(f"Неподдерживаемая schema_version={schema}")
        return cls(
            version=version,
            artifact_url=url,
            sha256=sha256,
            size=size,
            changelog=str(payload.get("changelog", ""))[:100_000],
            minimum_launcher_version=minimum,
            schema_version=schema,
        )

    def newer_than(self, current: str | None) -> bool:
        return current is None or version_key(self.version) > version_key(current)
