"""Operator-managed AI instructions keyed by a corporate ITSM ticket type.

The corporate ITSM adapter remains responsible for identifying the stable
``ticket_type``.  This store only lets an operator override the reviewed
instructions for that type without rebuilding the private Python package.
"""
from __future__ import annotations

import json
import logging
import threading
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from opencode_integration.context_builder import (
    MAX_ITSM_AI_INSTRUCTIONS_CHARS,
    MAX_ITSM_TICKET_TYPE_CHARS,
)


MAX_ITSM_PROMPT_RULES = 100
_log = logging.getLogger("web.itsm_prompts")


class ITSMPromptSettingsStore:
    """Persist non-secret ticket prompt overrides in the user data directory."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        rules, warning = self._load()
        return {
            "rules": rules,
            "warning": warning,
            "max_rules": MAX_ITSM_PROMPT_RULES,
            "max_ticket_type_chars": MAX_ITSM_TICKET_TYPE_CHARS,
            "max_prompt_chars": MAX_ITSM_AI_INSTRUCTIONS_CHARS,
            "precedence": "ui_override_then_corporate_hook",
        }

    def update(self, raw_rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if len(raw_rules) > MAX_ITSM_PROMPT_RULES:
            raise ValueError(
                f"Допустимо не более {MAX_ITSM_PROMPT_RULES} типов заявок"
            )
        rules: list[dict[str, str]] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_rules):
            if not isinstance(raw, Mapping):
                raise ValueError(f"Правило #{index + 1} должно быть объектом")
            unknown = set(raw) - {"ticket_type", "prompt"}
            if unknown:
                raise ValueError(
                    f"Правило #{index + 1} содержит неизвестные поля: "
                    + ", ".join(sorted(str(item) for item in unknown))
                )
            ticket_type = self._ticket_type(raw.get("ticket_type"), index)
            prompt = self._prompt(raw.get("prompt"), index)
            identity = ticket_type.casefold()
            if identity in seen:
                raise ValueError(
                    f"Тип заявки {ticket_type!r} указан больше одного раза"
                )
            seen.add(identity)
            rules.append({"ticket_type": ticket_type, "prompt": prompt})

        document = {"version": 1, "rules": rules}
        self._save(document)
        _log.info("ITSM AI prompt overrides updated count=%s", len(rules))
        return self.snapshot()

    def prompt_for(self, ticket_type: str) -> str | None:
        """Return an exact, case-insensitive UI override without caching it."""

        normalized = unicodedata.normalize("NFKC", str(ticket_type)).strip().casefold()
        if not normalized:
            return None
        rules, warning = self._load()
        if warning:
            _log.warning("ITSM prompt overrides ignored: %s", warning)
            return None
        for rule in rules:
            if rule["ticket_type"].casefold() == normalized:
                return rule["prompt"]
        return None

    @staticmethod
    def _ticket_type(value: Any, index: int) -> str:
        if not isinstance(value, str):
            raise ValueError(f"Тип заявки в правиле #{index + 1} должен быть строкой")
        result = unicodedata.normalize("NFKC", value).strip()
        if not result:
            raise ValueError(f"Укажите тип заявки в правиле #{index + 1}")
        if any(ord(char) < 32 or ord(char) == 127 for char in result):
            raise ValueError(
                f"Тип заявки в правиле #{index + 1} содержит управляющие символы"
            )
        if len(result) > MAX_ITSM_TICKET_TYPE_CHARS:
            raise ValueError(
                f"Тип заявки в правиле #{index + 1} длиннее "
                f"{MAX_ITSM_TICKET_TYPE_CHARS} символов"
            )
        return result

    @staticmethod
    def _prompt(value: Any, index: int) -> str:
        if not isinstance(value, str):
            raise ValueError(f"Prompt в правиле #{index + 1} должен быть строкой")
        result = unicodedata.normalize("NFKC", value)
        result = result.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not result:
            raise ValueError(f"Укажите prompt в правиле #{index + 1}")
        if len(result) > MAX_ITSM_AI_INSTRUCTIONS_CHARS:
            raise ValueError(
                f"Prompt в правиле #{index + 1} длиннее "
                f"{MAX_ITSM_AI_INSTRUCTIONS_CHARS} символов"
            )
        return result

    def _load(self) -> tuple[list[dict[str, str]], str]:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return [], ""
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                return [], f"Не удалось прочитать {self.path.name}: {type(exc).__name__}"
        if not isinstance(raw, Mapping) or raw.get("version") != 1:
            return [], f"Файл {self.path.name} имеет неподдерживаемый формат"
        candidates = raw.get("rules")
        if not isinstance(candidates, list):
            return [], f"В файле {self.path.name} отсутствует массив rules"
        try:
            # Reuse the same normalization as API writes so a manually edited
            # file can never bypass limits or duplicate detection.
            normalized: list[dict[str, str]] = []
            seen: set[str] = set()
            if len(candidates) > MAX_ITSM_PROMPT_RULES:
                raise ValueError("слишком много правил")
            for index, item in enumerate(candidates):
                if not isinstance(item, Mapping):
                    raise ValueError(f"правило #{index + 1} не является объектом")
                ticket_type = self._ticket_type(item.get("ticket_type"), index)
                prompt = self._prompt(item.get("prompt"), index)
                identity = ticket_type.casefold()
                if identity in seen:
                    raise ValueError(f"тип {ticket_type!r} продублирован")
                seen.add(identity)
                normalized.append({"ticket_type": ticket_type, "prompt": prompt})
            return normalized, ""
        except ValueError as exc:
            return [], f"Некорректный файл {self.path.name}: {exc}"

    def _save(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.path)
            except OSError as exc:
                raise ValueError(
                    f"Не удалось сохранить {self.path.name}: {type(exc).__name__}"
                ) from exc
