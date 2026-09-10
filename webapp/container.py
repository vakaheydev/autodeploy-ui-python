"""Composition root shared by API routes and background workers."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from config.environments import (
    OPENCODE_CONNECT_TIMEOUT_KEY,
    OPENCODE_REQUEST_TIMEOUT_KEY,
    OPENCODE_SERVER_PASSWORD_KEY,
    OPENCODE_SERVER_URL_KEY,
    OPENCODE_SERVER_USERNAME_KEY,
    OPENCODE_STARTUP_TIMEOUT_KEY,
)
from core.env_manager import EnvManager
from core.http_client import HttpClient
from core.reference_cache import ReferenceCache
from core.reference_resolver import ReferenceResolver
from core.run_storage import RunStorage
from forms.loader import register_all_forms
from forms.registry import FormRegistry
from handlers.http_reference_handler import HttpReferenceHandler
from handlers.local_reference_handler import LocalReferenceHandler
from opencode_integration.manager import OpenCodeManager, REQUIRED_AGENTS
from plugins.registry import PluginRegistry
from services.submit_service import SubmitService
from webapp.extensions import (
    extension_reference_handlers,
    load_search_catalogs,
    load_service_provider,
    load_ticket_provider,
    register_extension_forms,
    register_extension_plugins,
)
from webapp.environment_runtime import EnvironmentRuntime
from webapp.form_runtime import FormRuntime
from webapp.itsm_prompt_settings import ITSMPromptSettingsStore
from webapp.plugin_policy import PluginAIPolicyStore
from webapp.plugin_runtime import PluginRuntime
from webapp.security import ConfirmationStore, SubmissionStore, request_fingerprint
from webapp.settings import WebSettings
from webapp.ticket_runtime import TicketRuntime


class ApplicationContainer:
    def __init__(self, settings: WebSettings) -> None:
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.env_manager = EnvManager(settings.env_file)
        self.environments = EnvironmentRuntime(self.env_manager)
        self.reference_cache = ReferenceCache(settings.data_dir / "cache")
        self.run_storage = RunStorage(settings.data_dir / "runs.json")
        self.itsm_prompt_settings = ITSMPromptSettingsStore(
            settings.data_dir / "itsm-ai-prompts.json"
        )
        self.confirmations = ConfirmationStore()
        self.submissions = SubmissionStore()
        self.service_provider = load_service_provider(self.env_manager)
        self.ticket_provider = load_ticket_provider(self.env_manager)
        self.search_catalogs = load_search_catalogs(self.env_manager)
        registry = FormRegistry()
        # The registry is a desktop-compatible singleton.  Reset it at the web
        # composition boundary so repeated app factories/tests cannot retain a
        # form from a previously loaded private extension.
        registry.clear()
        register_all_forms()
        register_extension_forms(self.env_manager, registry)
        self.forms = FormRuntime(self)
        self.tickets = TicketRuntime(self)
        self.plugin_registry = PluginRegistry()
        register_extension_plugins(self.env_manager, self.plugin_registry)
        self.plugins = PluginRuntime(self, self.plugin_registry)
        self.plugin_ai_policy = PluginAIPolicyStore(
            settings.data_dir / "plugin-ai-policy.json",
            self.plugin_registry,
        )
        self._opencode_lock = threading.Lock()
        self.opencode_manager = self._build_opencode_manager()
        self.ai = None

    @staticmethod
    def fingerprint(form_id: str, environment: str, values, version: str) -> str:
        return request_fingerprint(form_id, environment, values, version)

    def new_http_client(self) -> HttpClient:
        return HttpClient(timeout=30, allow_redirects=False, max_response_bytes=10 * 1024 * 1024)

    def new_reference_resolver(self) -> ReferenceResolver:
        client = self.new_http_client()
        custom = extension_reference_handlers(
            self.env_manager, client, self.reference_cache
        )
        # Corporate handlers get first refusal for their sources/resources,
        # while built-in local and HTTP references remain available for forms
        # the extension does not own.
        handlers = list(custom or ()) + [
            LocalReferenceHandler(),
            HttpReferenceHandler(client, self.reference_cache, self.env_manager),
        ]
        return ReferenceResolver(handlers)

    def submit_service_for(self, client: HttpClient) -> SubmitService:
        return SubmitService(client, self.env_manager)

    def new_submit_service(self) -> SubmitService:
        return self.submit_service_for(self.new_http_client())

    def _build_opencode_manager(self) -> OpenCodeManager:
        values = self.env_manager.load()

        def number(key: str, default: float) -> float:
            try:
                return float(values.get(key, "") or default)
            except (TypeError, ValueError):
                return default

        project_agents = self.settings.project_root / ".opencode" / "agents"
        packaged_agents = Path(__file__).resolve().parent / "resources" / "opencode_agents"
        return OpenCodeManager(
            self.settings.project_root,
            server_url=values.get(OPENCODE_SERVER_URL_KEY, "http://127.0.0.1:4096"),
            connect_timeout=number(OPENCODE_CONNECT_TIMEOUT_KEY, 10.0),
            startup_timeout=number(OPENCODE_STARTUP_TIMEOUT_KEY, 20.0),
            request_timeout=number(OPENCODE_REQUEST_TIMEOUT_KEY, 120.0),
            username=values.get(OPENCODE_SERVER_USERNAME_KEY, "opencode"),
            password=values.get(OPENCODE_SERVER_PASSWORD_KEY, ""),
            runtime_dir=self.settings.data_dir / "opencode-runtime",
            agent_source_dir=(
                project_agents
                if all(
                    (project_agents / f"{name}.md").is_file()
                    for name in REQUIRED_AGENTS
                )
                else packaged_agents
            ),
            mcp_url=(
                f"http://127.0.0.1:{self.settings.port}/api/mcp"
                if self.settings.mcp_enabled
                else ""
            ),
        )
