# AutoDeploy MCP Server

AutoDeploy can publish a stateless MCP Streamable HTTP endpoint on the same
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

## Agent workflow

1. Call `search_forms` only when a form is not already known.
2. Call `get_form_schema` before proposing values. The returned field type tells
   whether the value is scalar (`select`) or an array (`multiselect`).
3. For a reference not already embedded in `options`, call
   `search_reference_options`. Store `value_key`; show `label_key`.
4. Call `calculate_form_state` after changing a controlling/dependent field.
5. Call `validate_form_values` and fix every returned error.
6. Optionally call `preview_form_submission` to inspect the server-built request.
7. Send the user to the web form for review and submission.

The MCP intentionally has no submit, deploy, update or delete tool. It may
prepare a validated preview, but only the user can confirm a side effect in the
web UI.

## Tools

- `get_system_status` — server, catalog, OpenCode and MCP availability.
- `list_environments` — authoritative environment keys.
- `search_forms` — keyword search over form metadata and field descriptions.
- `get_form_schema` — live form document, options, dependencies and version.
- `calculate_form_state` — recompute dynamic fields and normalized values.
- `search_reference_options` — paged select/multiselect reference search.
- `validate_form_values` — authoritative Python and domain validation.
- `preview_form_submission` — builds but does not send the request.
- `search_gravitee_objects` — API/application search through configured
  read-only corporate services.

Every tool advertises MCP read-only, idempotent and non-destructive annotations.
The endpoint never exposes the settings API or stored secret values.

## Minimal JSON-RPC check

```bash
curl -X POST http://127.0.0.1:8765/api/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

The endpoint is localhost-only because the parent FastAPI application rejects
non-local hosts and cross-origin browser writes.
