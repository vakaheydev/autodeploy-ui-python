"""Server-side activation boundary for browser environment switches."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass

from config.environments import ENVIRONMENT_MAP
from core.env_manager import EnvManager
from webapp.extensions import (
    EnvironmentChangeRejected,
    EnvironmentHook,
    load_environment_hook,
)


_log = logging.getLogger("web.environment")


@dataclass(frozen=True)
class EnvironmentActivation:
    previous_environment: str | None
    environment: str
    changed: bool
    hook_configured: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class EnvironmentRuntime:
    """Validate and serialize optional private environment preparation."""

    def __init__(self, env_manager: EnvManager) -> None:
        self._hook: EnvironmentHook | None = load_environment_hook(env_manager)
        self._lock = threading.Lock()

    @property
    def hook_configured(self) -> bool:
        return self._hook is not None

    def activate(
        self, previous_environment: str | None, environment: str
    ) -> EnvironmentActivation:
        current = str(environment).strip()
        previous = (
            str(previous_environment).strip()
            if previous_environment is not None
            else None
        )
        if current not in ENVIRONMENT_MAP:
            raise EnvironmentChangeRejected(
                f"Неизвестное окружение: {current or '<пусто>'}"
            )
        if previous is not None and previous not in ENVIRONMENT_MAP:
            raise EnvironmentChangeRejected(
                f"Неизвестное предыдущее окружение: {previous or '<пусто>'}"
            )

        changed = previous != current
        if not changed or self._hook is None:
            return EnvironmentActivation(
                previous_environment=previous,
                environment=current,
                changed=changed,
                hook_configured=self._hook is not None,
            )

        with self._lock:
            started = time.monotonic()
            _log.info(
                "environment hook started previous=%s current=%s",
                previous or "none",
                current,
            )
            try:
                self._hook(previous, current)
            except EnvironmentChangeRejected as exc:
                _log.warning(
                    "environment hook rejected previous=%s current=%s duration_ms=%d reason=%s",
                    previous or "none",
                    current,
                    int((time.monotonic() - started) * 1000),
                    exc,
                )
                raise
            except Exception as exc:
                _log.exception(
                    "environment hook failed previous=%s current=%s duration_ms=%d error_type=%s",
                    previous or "none",
                    current,
                    int((time.monotonic() - started) * 1000),
                    type(exc).__name__,
                )
                raise EnvironmentChangeRejected(
                    "Не удалось подготовить выбранное окружение. "
                    "Подробности записаны в лог сервера."
                ) from exc
            _log.info(
                "environment hook completed previous=%s current=%s duration_ms=%d",
                previous or "none",
                current,
                int((time.monotonic() - started) * 1000),
            )
        return EnvironmentActivation(
            previous_environment=previous,
            environment=current,
            changed=True,
            hook_configured=True,
        )
