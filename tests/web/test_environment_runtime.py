from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.env_manager import EnvManager
from webapp import extensions
from webapp.environment_runtime import EnvironmentRuntime


def configured_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook,
) -> EnvironmentRuntime:
    env = EnvManager(tmp_path / ".env")
    env.save({extensions.ENVIRONMENT_HOOK_KEY: "corp.environment:create"})
    monkeypatch.setattr(
        extensions, "import_callable", lambda _path: lambda _env: hook
    )
    return EnvironmentRuntime(env)


def test_activation_without_hook_validates_but_succeeds(tmp_path: Path) -> None:
    runtime = EnvironmentRuntime(EnvManager(tmp_path / ".env"))

    result = runtime.activate("test_int", "prod_int")

    assert result.as_dict() == {
        "previous_environment": "test_int",
        "environment": "prod_int",
        "changed": True,
        "hook_configured": False,
    }
    with pytest.raises(extensions.EnvironmentChangeRejected, match="Неизвестное"):
        runtime.activate("test_int", "missing")


def test_activation_calls_hook_only_for_a_real_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str | None, str]] = []
    runtime = configured_runtime(
        tmp_path, monkeypatch, lambda previous, current: calls.append((previous, current))
    )

    unchanged = runtime.activate("test_int", "test_int")
    changed = runtime.activate("test_int", "prod_int")

    assert unchanged.changed is False
    assert changed.hook_configured is True
    assert calls == [("test_int", "prod_int")]


def test_expected_rejection_is_kept_and_unexpected_error_is_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejected(_previous, _current):
        raise extensions.EnvironmentChangeRejected("VPN недоступен")

    runtime = configured_runtime(tmp_path, monkeypatch, rejected)
    with pytest.raises(extensions.EnvironmentChangeRejected, match="VPN недоступен"):
        runtime.activate("test_int", "prod_int")

    def crashed(_previous, _current):
        raise RuntimeError("private-token-value")

    runtime = configured_runtime(tmp_path, monkeypatch, crashed)
    with pytest.raises(extensions.EnvironmentChangeRejected) as caught:
        runtime.activate("test_int", "prod_int")
    assert "private-token-value" not in str(caught.value)
    assert "Подробности записаны в лог" in str(caught.value)


def test_hook_calls_are_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum_active = 0
    state_lock = threading.Lock()

    def hook(_previous, _current):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with state_lock:
            active -= 1

    runtime = configured_runtime(tmp_path, monkeypatch, hook)
    threads = [
        threading.Thread(
            target=runtime.activate,
            args=("test_int", environment),
        )
        for environment in ("prod_int", "regress_int")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert all(not thread.is_alive() for thread in threads)
    assert maximum_active == 1
