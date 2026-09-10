"""Безопасное логирование в консоль, ротационный файл и журнал UI."""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import stat
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque


_AUTH_RE = re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9+/._~=-]{6,}")
_SECRET_RE = re.compile(
    r"(?i)\b([a-z0-9_.-]*(?:api[_-]?key|token|pat|password|passwd|"
    r"client[_-]?secret|authorization|private[_-]?key|cookie)[a-z0-9_.-]*)"
    r"\b[\"']?\s*[:=]\s*[\"']?([^\"'\s,;}]{4,})"
)


def redact_log_text(value: object) -> str:
    """Редактирует только уже отформатированную строку; raw payload не логируется."""
    text = str(value).replace("\x00", "")
    text = _AUTH_RE.sub("[REDACTED_AUTHORIZATION]", text)
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def sanitize_server_log_line(value: object) -> str:
    """Фильтрует дочерний stdout OpenCode до terminal/file logging.

    Lifecycle, provider names, tool names и типы ошибок полезны. Prompt, message
    parts и structured output могут содержать ITSM/ADO/PII, поэтому целиком не
    протоколируются даже после regexp-redaction.
    """
    text = str(value).replace("\x00", "").strip()
    if not text:
        return ""
    lowered = text.casefold()
    sensitive_markers = (
        "begin_untrusted_",
        "end_untrusted_",
        "structured_output",
        "structuredoutput",
        "prompt=",
        '"prompt"',
        "parts=",
        '"parts"',
        "input=",
        '"input"',
        "output=",
        '"output"',
        "message=",
        '"message"',
        "content=",
        '"content"',
        "payload=",
        '"payload"',
        "body=",
        '"body"',
        "text=",
        '"text"',
        "system=",
        '"system"',
        "itsm_data",
        "ado_data",
    )
    if any(marker in lowered for marker in sensitive_markers):
        return "[CONTENT_REDACTED: possible prompt or model payload]"
    clean = "".join(char if char >= " " or char == "\t" else " " for char in text)
    return redact_log_text(clean)[:2000]


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


@dataclass(frozen=True)
class UILogEntry:
    sequence: int
    level: str
    text: str


class UILogBuffer(logging.Handler):
    """Потокобезопасный кольцевой буфер, который Tk читает через ``after``."""

    def __init__(self, capacity: int = 1000) -> None:
        super().__init__(logging.DEBUG)
        self._entries: Deque[UILogEntry] = deque(maxlen=capacity)
        self._sequence = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with self._lock:
            self._sequence += 1
            self._entries.append(UILogEntry(self._sequence, record.levelname, text))

    def since(self, sequence: int = 0) -> list[UILogEntry]:
        with self._lock:
            return [entry for entry in self._entries if entry.sequence > sequence]


UI_LOG_BUFFER = UILogBuffer()
_configured = False
OPENCODE_LOG_LEVELS = ("OFF", "ERROR", "WARNING", "INFO", "DEBUG")
_OPENCODE_LEVEL_VALUES: dict[str, int | None] = {
    "OFF": None,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}
_opencode_log_threshold: int | None = logging.INFO


def normalize_opencode_log_level(value: object) -> str:
    """Return a canonical OpenCode log level or reject an invalid setting."""
    normalized = str(value or "INFO").strip().upper()
    if normalized not in _OPENCODE_LEVEL_VALUES:
        raise ValueError(
            "AUTODEPLOY_OPENCODE_LOG_LEVEL должен быть одним из: "
            + ", ".join(OPENCODE_LOG_LEVELS)
        )
    return normalized


def set_opencode_log_level(value: object) -> str:
    """Change filtering for all OpenCode terminal, file and UI log channels."""
    global _opencode_log_threshold
    normalized = normalize_opencode_log_level(value)
    _opencode_log_threshold = _OPENCODE_LEVEL_VALUES[normalized]
    return normalized


class _OpenCodeOnly(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == "opencode" or record.name.startswith("opencode.")


class _ChannelLevel(logging.Filter):
    """Use one operator-selected threshold for every ``opencode.*`` record."""

    def __init__(self, default_level: int) -> None:
        super().__init__()
        self.default_level = default_level

    def filter(self, record: logging.LogRecord) -> bool:
        is_opencode = record.name == "opencode" or record.name.startswith("opencode.")
        threshold = _opencode_log_threshold if is_opencode else self.default_level
        return threshold is not None and record.levelno >= threshold


def configure_logging(
    log_dir: Path | None = None,
    *,
    opencode_level: object | None = None,
) -> Path:
    """Настраивает handlers один раз и возвращает путь текущего файла лога."""
    global _configured
    set_opencode_log_level(
        opencode_level
        if opencode_level is not None
        else os.environ.get("AUTODEPLOY_OPENCODE_LOG_LEVEL", "INFO")
    )
    target_dir = Path(log_dir or Path(__file__).resolve().parent.parent / "logs")
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / "autodeploy.log"
    if _configured:
        return log_path

    detailed = RedactingFormatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    compact = RedactingFormatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    stream = logging.StreamHandler()
    # Handler levels stay at DEBUG so the filter can independently apply the
    # selected OpenCode threshold while retaining INFO for other console logs.
    stream.setLevel(logging.DEBUG)
    stream.setFormatter(compact)
    stream.addFilter(_ChannelLevel(logging.INFO))
    rotating = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    rotating.setLevel(logging.DEBUG)
    rotating.setFormatter(detailed)
    rotating.addFilter(_ChannelLevel(logging.DEBUG))
    # Logs can contain internal identifiers and error details.  Keep them
    # private on POSIX; Windows applies the user's ACL to the profile folder.
    try:
        os.chmod(log_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    UI_LOG_BUFFER.setFormatter(compact)
    UI_LOG_BUFFER.addFilter(_OpenCodeOnly())
    UI_LOG_BUFFER.addFilter(_ChannelLevel(logging.DEBUG))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Точка входа может вызываться повторно в тестах/embedded-сценариях.
    for handler in (stream, rotating, UI_LOG_BUFFER):
        if handler not in root.handlers:
            root.addHandler(handler)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _configured = True
    return log_path
