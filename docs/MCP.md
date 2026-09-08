# AutoDeploy MCP Server

AutoDeploy can publish an MCP Streamable HTTP endpoint on the same
localhost port as the REST API and React client:

```text
http://127.0.0.1:8765/api/mcp
```

Enable it in `.env` or on the **Настройки** page and restart the Python server:

```dotenv
AUTODEPLOY_MCP_ENABLED=true
```

When enabled, the isolated OpenCode runtime receives a remote MCP entry named
`autodeploy`. New Gravitee Copilot sessions get an exact allowlist of its tools.
Disable the flag and restart to remove the entry. Existing OpenCode sessions
must be recreated after changing the setting.

The JSON-RPC transport does not require a server-side MCP connection object.
Three workflow tools do use an opaque `workflow_id` to reach the owning Copilot
session, its lazy form-search session and its persistent drafts.

## Agent workflow

1. Copilot calls `semantic_search_forms` only when the request concerns a form
   and the exact form is not already established. The complete catalog is built
   and stored only on that first call; later calls reuse the same `none`-thinking
   OpenCode search session.
2. Call `get_form_schema` before proposing values. The returned field type tells
   whether the value is scalar (`select`) or an array (`multiselect`).
3. For a reference not already embedded in `options`, call
   `search_reference_options`. Store `value_key`; show `label_key`.
4. Call `calculate_form_state` after changing a controlling/dependent field.
5. Call `prepare_form_draft` with evidenced values, source and confidence.
   Python resolves references and performs authoritative validation.
6. Explain any returned validation gaps and send the user to the draft link.
7. The user reviews values in the web form. Normal preview/confirmation/submit
   remains separate and human-controlled.

The MCP intentionally has no submit, deploy or external update/delete tool. It
may prepare a persistent local draft, but only the user can confirm a side effect
in the web UI.

## Tools

- `get_system_status` — server, catalog, OpenCode and MCP availability.
- `list_environments` — authoritative environment keys.
- `search_forms` — keyword search over form metadata and field descriptions.
- `semantic_search_forms` — query the owning workflow's persistent, lazy,
  `none`-thinking semantic form-search session.
- `get_form_schema` — live form document, options, dependencies and version.
- `calculate_form_state` — recompute dynamic fields and normalized values.
- `search_reference_options` — paged select/multiselect reference search.
- `validate_form_values` — authoritative Python and domain validation.
- `preview_form_submission` — builds but does not send the request.
- `prepare_form_draft` — creates or revises a persistent, Python-validated local
  draft; it never submits or performs an external write.
- `research_repository` — delegates one bounded complex question to an isolated
  read-only JSON Repository Researcher and deletes that session afterwards.
- `search_gravitee_objects` — API/application search through the catalogs from
  `AUTODEPLOY_SEARCH_CATALOG_FACTORY` and their configured read-only reference
  handlers.

Every built-in workflow tool is non-destructive and idempotent. `prepare_form_draft` advertises
`readOnlyHint=false` because it stores persistent local state; all other tools
are read-only. The endpoint never exposes the settings API or stored secret
values and contains no submit/deploy tool.

`search_forms` remains available to generic MCP clients, but it is deliberately
absent from the web Copilot session allowlist. Therefore an unknown form in the
chat can only be selected through the workflow-owned `semantic_search_forms`
session.

## Corporate plugin tools

Corporate custom pages use an independent, fail-closed tool surface. Nothing is
published until the operator enables global AI visibility and the specific
plugin in **Настройки -> Плагины**. Then:

- `list_plugins` lists only visible plugins;
- `get_plugin_page` returns live safe fields/widgets and non-denied operations;
- `calculate_plugin_state` recalculates conditional fields and dynamic widgets;
- `search_plugin_reference_options` resolves `SELECT/MULTISELECT` values lazily;
- `validate_plugin_values` runs authoritative Python validation;
- each operation configured as `allow` or `manual` receives its own stable MCP
  tool name and JSON input schema.

`allow` becomes an exact OpenCode allow rule. `manual` becomes an exact ask rule
and requires approval on every call. `deny` removes the tool and is checked once
more during dispatch, protecting an old session after revocation. Tool
annotations (`readOnlyHint`, `idempotentHint`, `openWorldHint`) describe behavior
but never grant authority.

Plugin operations may be external writes when a corporate author defines them;
therefore the non-destructive guarantee for built-in workflow tools does not
apply to dynamic plugin tools. Their authority is always explicit and per
operation. Full private authoring guidance is in
[corp/PLUGINS.md](corp/PLUGINS.md).

## Minimal JSON-RPC check

```bash
curl -X POST http://127.0.0.1:8765/api/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

The endpoint is localhost-only because the parent FastAPI application rejects
non-local hosts and cross-origin browser writes.

## Agent architecture

New web Copilot sessions use the MCP-native draft flow and do not invoke the old
extractor. The separate extractor remains only as a desktop/legacy compatibility
path. Session topology, lifecycle and trust boundaries are documented in
[AI_AGENT_ARCHITECTURE.md](AI_AGENT_ARCHITECTURE.md).
