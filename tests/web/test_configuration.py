from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.env_manager import EnvManager
from webapp.configuration import settings_snapshot, update_settings
from webapp.settings import WebSettings


class ManagerStub:
    def __init__(self) -> None:
        self.configured: dict[str, object] = {}

    def configure(self, **values) -> None:
        self.configured = values


def test_secret_settings_are_write_only(tmp_path: Path) -> None:
    env = EnvManager(tmp_path / ".env")
    manager = ManagerStub()
    result = update_settings(
        env,
        manager,  # type: ignore[arg-type]
        {
            "LOGIN": "operator",
            "TFS_TOKEN": "top-secret-value",
            "OPENCODE_SERVER_URL": "http://127.0.0.1:4096",
        },
        [],
    )

    serialized = json.dumps(result)
    assert "top-secret-value" not in serialized
    token = next(
        field
        for group in result["groups"]
        for field in group["fields"]
        if field["key"] == "TFS_TOKEN"
    )
    assert token["configured"] is True
    assert token["value"] is None
    assert env.get("TFS_TOKEN") == "top-secret-value"
    assert manager.configured["server_url"] == "http://127.0.0.1:4096"


def test_secret_requires_explicit_clear(tmp_path: Path) -> None:
    env = EnvManager(tmp_path / ".env")
    env.save({"TFS_TOKEN": "sensitive-token-123"})
    manager = ManagerStub()

    with pytest.raises(ValueError, match="явную очистку"):
        update_settings(env, manager, {"TFS_TOKEN": ""}, [])  # type: ignore[arg-type]

    result = update_settings(env, manager, {}, ["TFS_TOKEN"])  # type: ignore[arg-type]
    assert env.get("TFS_TOKEN") == ""
    assert "sensitive-token-123" not in json.dumps(result)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"UNKNOWN": "value"}, "Неизвестные настройки"),
        ({"OPENCODE_SERVER_URL": "https://remote.example:4096"}, "localhost"),
        ({"OPENCODE_PROVIDER_ID": "corp", "OPENCODE_MODEL_ID": ""}, "задаются вместе"),
        ({"OPENCODE_CONNECT_TIMEOUT": "0"}, "минимум"),
    ],
)
def test_settings_validation(tmp_path: Path, updates: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        update_settings(
            EnvManager(tmp_path / ".env"),
            ManagerStub(),  # type: ignore[arg-type]
            updates,
            [],
        )


def test_web_settings_reads_restart_values_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    EnvManager(env_file).save({
        "AUTODEPLOY_PORT": "9876",
        "AUTODEPLOY_OPENCODE_AUTO_CONNECT": "false",
        "AUTODEPLOY_OPEN_BROWSER": "false",
        "AUTODEPLOY_MCP_ENABLED": "true",
    })
    monkeypatch.setenv("AUTODEPLOY_ENV_FILE", str(env_file))
    monkeypatch.delenv("AUTODEPLOY_PORT", raising=False)
    monkeypatch.delenv("AUTODEPLOY_OPENCODE_AUTO_CONNECT", raising=False)
    monkeypatch.delenv("AUTODEPLOY_OPEN_BROWSER", raising=False)
    monkeypatch.delenv("AUTODEPLOY_MCP_ENABLED", raising=False)

    settings = WebSettings.load()
    assert settings.port == 9876
    assert settings.auto_connect_opencode is False
    assert settings.open_browser is False
    assert settings.mcp_enabled is True


def test_snapshot_never_contains_saved_secrets(tmp_path: Path) -> None:
    env = EnvManager(tmp_path / ".env")
    env.save({"ITSM_PASSWORD": "itsm-password", "GRAVITEE_TOKEN_PROD_INT": "token"})
    snapshot = json.dumps(settings_snapshot(env))
    assert "itsm-password" not in snapshot
    assert '"token"' not in snapshot
