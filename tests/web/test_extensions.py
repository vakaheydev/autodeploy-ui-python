from __future__ import annotations

from pathlib import Path

import pytest

from core.env_manager import EnvManager
from forms.fields import ReferenceConfig
from webapp import extensions


def _catalogs() -> dict[str, ReferenceConfig]:
    return {
        "api": ReferenceConfig(
            source="corp_http",
            resource="api_catalog",
            value_key="uuid",
            label_key="display_name",
            search_keys=("context_path", "display_name"),
        ),
        "application": ReferenceConfig(
            source="corp_http",
            resource="application_catalog",
            value_key="client_id",
            label_key="display_name",
            search_keys=("azp", "display_name"),
        ),
    }


def test_search_catalog_factory_replaces_public_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = EnvManager(tmp_path / ".env")
    env.save({
        extensions.SEARCH_CATALOG_FACTORY_KEY:
            "corp_autodeploy.search:create_catalogs",
    })
    expected = _catalogs()

    def factory(received_env: EnvManager):
        assert received_env is env
        return expected

    monkeypatch.setattr(extensions, "import_callable", lambda _path: factory)

    assert extensions.load_search_catalogs(env) == expected


def test_environment_hook_factory_receives_env_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = EnvManager(tmp_path / ".env")
    env.save({
        extensions.ENVIRONMENT_HOOK_KEY:
            "corp_autodeploy.environment:create_environment_hook",
    })
    calls: list[tuple[str | None, str]] = []

    def factory(received_env: EnvManager):
        assert received_env is env
        return lambda previous, current: calls.append((previous, current))

    monkeypatch.setattr(extensions, "import_callable", lambda _path: factory)

    hook = extensions.load_environment_hook(env)
    assert hook is not None
    hook("test_int", "prod_int")
    assert calls == [("test_int", "prod_int")]


def test_environment_hook_factory_must_return_callable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = EnvManager(tmp_path / ".env")
    env.save({extensions.ENVIRONMENT_HOOK_KEY: "corp.environment:create"})
    monkeypatch.setattr(
        extensions, "import_callable", lambda _path: lambda _env: object()
    )

    with pytest.raises(TypeError, match="вернуть callable"):
        extensions.load_environment_hook(env)


@pytest.mark.parametrize(
    ("configured", "message"),
    [
        ({"api": _catalogs()["api"]}, "не настроил: application"),
        ({**_catalogs(), "unknown": _catalogs()["api"]}, "неизвестные типы"),
        ({"api": object(), "application": _catalogs()["application"]}, "ReferenceConfig"),
    ],
)
def test_search_catalog_factory_contract_is_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured: dict[str, object],
    message: str,
) -> None:
    env = EnvManager(tmp_path / ".env")
    env.save({extensions.SEARCH_CATALOG_FACTORY_KEY: "corp.search:create"})
    monkeypatch.setattr(
        extensions, "import_callable", lambda _path: lambda _env: configured
    )

    with pytest.raises((TypeError, ValueError), match=message):
        extensions.load_search_catalogs(env)
