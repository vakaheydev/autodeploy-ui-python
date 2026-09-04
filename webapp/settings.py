"""Runtime settings for the local web server.

Secrets are read server-side from the configured ``.env`` file.  This module
never exposes their values through an HTTP model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.env_manager import ENV_FILE_OVERRIDE


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_user_data_dir() -> Path:
    """Writable per-user state directory used outside the source checkout."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "GraviteeAutoDeploy"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "gravitee-autodeploy"


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class WebSettings:
    host: str
    port: int
    project_root: Path
    data_dir: Path
    env_file: Path
    static_dir: Path
    log_dir: Path
    max_request_bytes: int
    auto_connect_opencode: bool
    open_browser: bool

    @classmethod
    def load(cls) -> "WebSettings":
        project_root = Path(os.environ.get("AUTODEPLOY_PROJECT_ROOT", PROJECT_ROOT)).resolve()
        data_dir = Path(
            os.environ.get("AUTODEPLOY_DATA_DIR", default_user_data_dir())
        ).expanduser().resolve()
        legacy_env = project_root / ".env"
        env_file = Path(
            os.environ.get(
                ENV_FILE_OVERRIDE,
                legacy_env if legacy_env.is_file() else data_dir / "config" / ".env",
            )
        ).expanduser().resolve()
        static_dir = Path(
            os.environ.get(
                "AUTODEPLOY_STATIC_DIR",
                Path(__file__).resolve().parent / "static",
            )
        ).resolve()
        host = os.environ.get("AUTODEPLOY_HOST", "127.0.0.1").strip()
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError(
                "Web server разрешено запускать только на 127.0.0.1/localhost"
            )
        port = _positive_int(os.environ.get("AUTODEPLOY_PORT"), 8765)
        if port > 65535:
            raise ValueError("AUTODEPLOY_PORT должен быть от 1 до 65535")
        return cls(
            host=host,
            port=port,
            project_root=project_root,
            data_dir=data_dir,
            env_file=env_file,
            static_dir=static_dir,
            log_dir=Path(
                os.environ.get("AUTODEPLOY_LOG_DIR", data_dir / "logs")
            ).resolve(),
            max_request_bytes=_positive_int(
                os.environ.get("AUTODEPLOY_MAX_REQUEST_BYTES"), 2 * 1024 * 1024
            ),
            auto_connect_opencode=os.environ.get(
                "AUTODEPLOY_OPENCODE_AUTO_CONNECT", "true"
            ).strip().casefold() not in {"0", "false", "no", "off"},
            open_browser=os.environ.get(
                "AUTODEPLOY_OPEN_BROWSER", "true"
            ).strip().casefold() not in {"0", "false", "no", "off"},
        )
