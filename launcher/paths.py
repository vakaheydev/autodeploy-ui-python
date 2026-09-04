from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_install_root() -> Path:
    override = os.environ.get("AUTODEPLOY_INSTALL_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return (base / "GraviteeAutoDeploy").resolve()


@dataclass(frozen=True)
class InstallPaths:
    root: Path

    @classmethod
    def create(cls, root: Path | None = None) -> "InstallPaths":
        return cls(Path(root or default_install_root()).expanduser().resolve())

    @property
    def versions(self) -> Path:
        return self.root / "versions"

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def env_file(self) -> Path:
        return self.config / ".env"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def state_file(self) -> Path:
        return self.root / "current.json"

    @property
    def lock_file(self) -> Path:
        return self.root / ".update.lock"

    def ensure(self) -> None:
        for path in (self.root, self.versions, self.downloads, self.config, self.data, self.logs):
            path.mkdir(parents=True, exist_ok=True)
