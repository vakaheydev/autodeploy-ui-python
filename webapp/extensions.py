"""Stable boundary for private corporate implementations.

Set ``AUTODEPLOY_SERVICE_PROVIDER=company.module:create_services`` in ``.env``.
The closed module can then be upgraded independently from the public web core.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol

from core.env_manager import EnvManager
from core.http_client import HttpClient
from forms.fields import ReferenceConfig
from services.gravitee_service import GraviteeService
from services.itsm_service import ITSMService
from services.tfs_service import TfsService


SERVICE_PROVIDER_KEY = "AUTODEPLOY_SERVICE_PROVIDER"
FORM_REGISTRAR_KEY = "AUTODEPLOY_FORM_REGISTRAR"
REFERENCE_HANDLER_FACTORY_KEY = "AUTODEPLOY_REFERENCE_HANDLER_FACTORY"
SEARCH_CATALOG_FACTORY_KEY = "AUTODEPLOY_SEARCH_CATALOG_FACTORY"
ENVIRONMENT_HOOK_KEY = "AUTODEPLOY_ENVIRONMENT_HOOK"
PLUGIN_REGISTRAR_KEY = "AUTODEPLOY_PLUGIN_REGISTRAR"
TICKET_PROVIDER_KEY = "AUTODEPLOY_TICKET_PROVIDER"

_SEARCH_KINDS = frozenset({"api", "application"})


@dataclass(frozen=True)
class RuntimeServices:
    itsm: Any
    tfs: Any
    gravitee: Any


class ServiceProvider(Protocol):
    def __call__(
        self, env_manager: EnvManager, http_client: HttpClient
    ) -> RuntimeServices:
        ...


class EnvironmentHook(Protocol):
    """Private callback executed before the browser commits an environment."""

    def __call__(
        self, previous_environment: str | None, environment: str
    ) -> None:
        ...


class EnvironmentChangeRejected(ValueError):
    """A safe, user-facing reason why a corporate hook rejected a switch."""


def default_services(
    env_manager: EnvManager, http_client: HttpClient
) -> RuntimeServices:
    """Public no-network defaults; corporate builds replace this factory."""
    return RuntimeServices(
        itsm=ITSMService(env_manager, http_client),
        tfs=TfsService(env_manager, http_client),
        gravitee=GraviteeService(env_manager, http_client),
    )


def import_callable(import_path: str) -> Callable[..., Any]:
    module_name, separator, attribute = str(import_path).strip().partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("Import path должен иметь формат package.module:callable")
    value = getattr(importlib.import_module(module_name), attribute)
    if not callable(value):
        raise TypeError(f"{import_path!r} не является callable")
    return value


def load_service_provider(env_manager: EnvManager) -> ServiceProvider:
    path = env_manager.get(SERVICE_PROVIDER_KEY, "").strip()
    return import_callable(path) if path else default_services


def load_environment_hook(env_manager: EnvManager) -> EnvironmentHook | None:
    """Load ``factory(env_manager) -> hook(previous, current)`` from ``.env``."""
    path = env_manager.get(ENVIRONMENT_HOOK_KEY, "").strip()
    if not path:
        return None
    hook = import_callable(path)(env_manager)
    if not callable(hook):
        raise TypeError(
            "Фабрика hook переключения окружения должна вернуть callable"
        )
    return hook


def register_extension_forms(env_manager: EnvManager, registry: Any) -> None:
    """Let a private package register/replace forms without editing public core."""
    path = env_manager.get(FORM_REGISTRAR_KEY, "").strip()
    if path:
        import_callable(path)(registry)


def register_extension_plugins(env_manager: EnvManager, registry: Any) -> None:
    """Let a private package register custom pages without patching the core."""
    path = env_manager.get(PLUGIN_REGISTRAR_KEY, "").strip()
    if path:
        import_callable(path)(registry)


def load_ticket_provider(env_manager: EnvManager) -> Any | None:
    """Load ``factory(env_manager) -> TicketProvider`` from the private package."""

    path = env_manager.get(TICKET_PROVIDER_KEY, "").strip()
    if not path:
        return None
    provider = import_callable(path)(env_manager)
    required = (
        "get_list_configuration",
        "load_current_tickets",
        "find_tickets",
        "load_ticket_card_by_id",
    )
    missing = [name for name in required if not callable(getattr(provider, name, None))]
    if missing:
        raise TypeError(
            "Фабрика заявок вернула объект без методов: " + ", ".join(missing)
        )
    return provider


def extension_reference_handlers(
    env_manager: EnvManager,
    http_client: HttpClient,
    cache: Any,
) -> Iterable[Any] | None:
    """Load private reference handlers when a corporate factory is configured."""
    path = env_manager.get(REFERENCE_HANDLER_FACTORY_KEY, "").strip()
    if not path:
        return None
    result = import_callable(path)(env_manager, http_client, cache)
    if result is None:
        return ()
    if not isinstance(result, Iterable):
        raise TypeError("Reference handler factory должен вернуть iterable")
    return result


def default_search_catalogs() -> dict[str, ReferenceConfig]:
    """Safe standalone catalogs used when no private search factory is configured."""
    return {
        "api": ReferenceConfig(
            source="local",
            resource="gravitee_apis.json",
            value_key="id",
            label_key="name",
            search_keys=("name", "context_path", "id"),
        ),
        "application": ReferenceConfig(
            source="http",
            resource="applications",
            value_key="id",
            label_key="name",
            search_keys=("name", "azp", "id"),
        ),
    }


def load_search_catalogs(env_manager: EnvManager) -> dict[str, ReferenceConfig]:
    """Load the complete API/application search catalog map from an extension."""
    path = env_manager.get(SEARCH_CATALOG_FACTORY_KEY, "").strip()
    if not path:
        return default_search_catalogs()

    result = import_callable(path)(env_manager)
    if not isinstance(result, Mapping):
        raise TypeError("Search catalog factory должен вернуть mapping")

    keys = {str(key) for key in result}
    missing = sorted(_SEARCH_KINDS - keys)
    unexpected = sorted(keys - _SEARCH_KINDS)
    if missing:
        raise ValueError(
            "Search catalog factory не настроил: " + ", ".join(missing)
        )
    if unexpected:
        raise ValueError(
            "Search catalog factory вернул неизвестные типы: "
            + ", ".join(unexpected)
        )

    catalogs: dict[str, ReferenceConfig] = {}
    for kind in sorted(_SEARCH_KINDS):
        reference = result[kind]
        if not isinstance(reference, ReferenceConfig):
            raise TypeError(
                f"Справочник поиска {kind!r} должен быть ReferenceConfig"
            )
        if not reference.source or not reference.resource:
            raise ValueError(
                f"Справочник поиска {kind!r} должен задавать source и resource"
            )
        if not reference.search_keys:
            raise ValueError(
                f"Справочник поиска {kind!r} должен задавать search_keys"
            )
        catalogs[kind] = reference
    return catalogs
