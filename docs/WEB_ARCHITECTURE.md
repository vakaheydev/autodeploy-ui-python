# Web architecture

## Principle

The React application is a renderer and interaction client. It does not own a
second copy of business rules. For every form the Python server remains the
source of truth for:

- form and field definitions, defaults and conditional visibility;
- SELECT/MULTISELECT reference semantics and dependent references;
- coercion, generic validation and each form's custom `validate()`;
- `build_payload()`, endpoint, HTTP method, auth and headers;
- `pre_submit()` and all network side effects;
- confirmation, result formatting, polling and run history;
- ITSM/TFS/Gravitee and private corporate integrations;
- AI orchestration, Python-owned drafts and the mandatory human review boundary.

The same separation also supports corporate custom pages. A private
`PluginDefinition` declares shared form fields, dynamic safe widgets and named
Python operations. `PluginRuntime` owns conditions, references, validation,
service injection and operation execution; React remains a generic renderer.

The same FastAPI process serves both `/api/v1/*` and the prebuilt static React
application. There is no Node process on a user's machine.

## Request flow

1. `GET /api/v1/forms/{id}` serializes the existing `BaseForm` into a UI-safe
   document and returns a short schema version hash.
2. React renders supported `FieldType` values generically.
3. Every value change is sent to `/state`; Python evaluates callable conditions
   and returns the new visible schema.
4. Reference values are requested from the field-specific `/options` endpoint.
   `ReferenceConfig.value_key` is the stored/submitted value, `label_key` is the
   displayed text, and `search_keys` defines matching fields. Consequently an API
   can be searched by `context_path` while its ID remains the submitted value.
   A local dictionary is embedded only when it contains at most 99 records and
   its public JSON is at most 64 KiB; larger dictionaries are searched and paged
   by Python. The endpoint always adds currently selected records to the result,
   so a new search cannot silently clear SELECT/MULTISELECT values.
   For a dependent reference, `depends_on_field` is resolved server-side from
   the full selected parent record; the browser still stores only its
   `value_key` and never has to reproduce that lookup rule.
5. `/validate` and `/preview` execute server validation and `build_payload()`.
   Structural errors already carry their field path. Custom validators should
   return `self.validation_error("field_key", "message")`; legacy strings are
   matched by field key/label when possible. React renders these messages inline
   and scrolls/focuses the first invalid field.
6. Destructive forms receive a short-lived, one-use confirmation capability.
7. `/submit` revalidates everything and calls the original Python submit hooks.
   Browser-provided payloads and endpoints are never trusted.

Unknown fields, stale form versions, wrong reference IDs and invalid dependent
values are rejected by the server. A browser cannot bypass those checks.

## Compatibility with desktop forms

Existing forms require no rewrite for their main workflow. The web runtime calls:

```text
fields -> validate -> build_payload -> pre_submit -> HTTP
       -> get_result_status/build_result_content -> poll hooks
```

`self.screen.get_field_item(s)` inside `pre_submit()` is supported through a
headless compatibility context containing the fully resolved reference objects.
Every request-scoped form also receives the selected environment as the plain
string `self.current_environment`; use it instead of
`self.screen.app.current_environment.get()`.

For gradual migration, `self.apply_form_data({...})` and the legacy
`self.screen.apply_form_data({...})` are supported while executing a
`ServerAction` or `fetch_from_itsm()`. The web context accumulates that patch and
returns it to React; unknown field keys are ignored as in `FormScreen`. Calling
it during validation, payload construction or submit remains an error because
the browser values have already entered validation/confirmation at that point.
The original Tkinter entry point remains `python main.py`.

Tkinter-only `CustomButton` callbacks may open dialogs and therefore cannot be
executed safely on a server. They are shown disabled with a migration hint. Move
their UI-independent behavior into `get_server_actions()`:

```python
from forms.base_form import ServerAction

def get_server_actions(self):
    return [ServerAction(
        action_id="discover",
        label="Найти значения",
        handler=self._discover,  # (environment, form_data) -> mapping
        confirmation_text="Запустить поиск?",  # optional one-use confirmation
    )]
```

The handler stays in Python and can return `{"message": ..., "values": ...,
"data": ...}`. Returned values are merged into the rendered form.

## Corporate isolation points

Public code contains safe placeholder integrations. Private implementation is
kept in a separate wheel and selected from server-side `.env`:

- `AUTODEPLOY_SERVICE_PROVIDER=corp.services:create_services`
- `AUTODEPLOY_FORM_REGISTRAR=corp.forms:register_forms`
- `AUTODEPLOY_PLUGIN_REGISTRAR=corp.plugins:register_plugins`
- `AUTODEPLOY_REFERENCE_HANDLER_FACTORY=corp.references:create_handlers`
- `AUTODEPLOY_SEARCH_CATALOG_FACTORY=corp.search:create_search_catalogs`
- `AUTODEPLOY_ENVIRONMENT_HOOK=corp.environment:create_environment_hook`

Последняя граница выполняет корпоративную подготовку до фиксации выбранного
окружения в браузере. Полный private-package handbook, включая точные контракты
форм, сервисов, справочников и environment hook, изолирован в
[corp/](corp/README.md).

An extension wheel can be added to a release with
`scripts/build_release.py --extra-wheel corp_autodeploy.whl`. It is installed
offline beside the public application. The frontend never imports or downloads
private modules.

Example registrar:

```python
def register_forms(registry):
    registry.register(CorporateCreateApiForm())  # replaces same form_id
```

Example reference factory:

```python
def create_handlers(env_manager, http_client, cache):
    return [CorporateReferenceHandler(env_manager, http_client, cache)]
```

The global API/application search catalogs are declared separately from their
data handlers:

```python
from forms.fields import ReferenceConfig

def create_search_catalogs(env_manager):
    return {
        "api": ReferenceConfig(
            source="corp_http", resource="gravitee_apis",
            value_key="id", label_key="name",
            search_keys=("context_path", "name", "id"),
        ),
        "application": ReferenceConfig(
            source="corp_http", resource="gravitee_applications",
            value_key="id", label_key="name",
            search_keys=("azp", "name", "id"),
        ),
    }
```

This factory selects logical catalogs; the reference handler remains solely
responsible for private URLs, credentials, loading and caching.

Corporate handlers are checked first. Built-in local/HTTP handlers remain as
fallbacks, so registering a corporate remote source does not disable small local
reference lists used by unrelated forms.

This boundary lets public server/frontend updates be merged without editing
closed ITSM, TFS, endpoint or reference implementations.

## API surface

Interactive OpenAPI documentation is available locally at `/api/docs`.
Important resources are:

- `/api/v1/health`, `/catalog`, `/forms`, `/forms/{id}`;
- `/forms/{id}/state|validate|preview|submit`;
- `/forms/{id}/fields/{path}/options` and `/ticket`;
- `/forms/{id}/actions/{action_id}`;
- `/runs`, `/submissions/{id}/poll`, `/search`;
- `/opencode/*` and `/ai/*` for OpenCode chat, draft review and compatibility
  extraction endpoints;
- `/settings` for whitelisted configuration with write-only secrets;
- `/plugins`, `/plugins/{id}/state|validate|operations/*` and plugin reference
  options for corporate custom pages;
- `/plugins/ai-policy` for global, per-plugin and per-operation AI access;
- `/api/mcp` for the optional Streamable HTTP MCP endpoint.

All request models reject unknown properties. Breaking API changes require a new
prefix (`/api/v2`), so future MCP or other clients can rely on `/api/v1`.

## Security model

- The application binds only to `127.0.0.1`/`localhost`.
- Host and browser Origin are checked; cross-site browser requests are rejected.
- CSP, frame denial, MIME sniffing protection and restrictive permissions headers
  are emitted for all routes.
- Secrets remain in the launcher-controlled `.env` and are never returned by an
  endpoint. OpenCode provider credentials remain in OpenCode configuration.
- Update URLs require HTTPS (loopback HTTP is accepted only for tests), embedded
  URL credentials are rejected, TFS Authorization is stripped on cross-host
  redirects, archive size/path/symlink limits are enforced, and SHA-256 is checked
  before installation.
- Each application version has its own virtual environment. Activation is an
  atomic pointer write; failed startup triggers rollback to the previous version.

The optional MCP delegates to this same `FormRuntime`, so it cannot bypass form
versions, reference resolution or Python validation. It can store a persistent
non-submitting draft; submission remains a separate human action in the web UI.
Enable it with `AUTODEPLOY_MCP_ENABLED=true`; detailed tool guidance is in
[MCP.md](MCP.md).

Corporate plugin operations are exposed as one exact MCP tool per operation,
never through a wildcard dispatcher. They are absent by default. Operators can
choose `deny`, `manual` or `allow` in web settings; MCP dispatch rechecks deny so
revocation also protects stale sessions. The corporate authoring contract lives
in [corp/PLUGINS.md](corp/PLUGINS.md).

The web Copilot starts without the form catalog. On demand it invokes a separate
persistent `none`-thinking form-search session, then creates Python-validated
drafts directly through MCP. An isolated short-lived Researcher handles only
complex JSON Repository investigations. The old extractor path remains for
desktop compatibility. See [AI_AGENT_ARCHITECTURE.md](AI_AGENT_ARCHITECTURE.md).
