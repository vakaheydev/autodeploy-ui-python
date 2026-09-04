"""Stable boundary for private corporate implementations.

Set ``AUTODEPLOY_SERVICE_PROVIDER=company.module:create_services`` in ``.env``.
The closed module can then be upgraded independently from the public web core.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from core.env_manager import EnvManager
from core.http_client import HttpClient
from services.gravitee_service import GraviteeService
from services.itsm_service import ITSMService
from services.tfs_service import TfsService


SERVICE_PROVIDER_KEY = "AUTODEPLOY_SERVICE_PROVIDER"
FORM_REGISTRAR_KEY = "AUTODEPLOY_FORM_REGISTRAR"
REFERENCE_HANDLER_FACTORY_KEY = "AUTODEPLOY_REFERENCE_HANDLER_FACTORY"


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


def register_extension_forms(env_manager: EnvManager, registry: Any) -> None:
    """Let a private package register/replace forms without editing public core."""
    path = env_manager.get(FORM_REGISTRAR_KEY, "").strip()
    if path:
        import_callable(path)(registry)


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
