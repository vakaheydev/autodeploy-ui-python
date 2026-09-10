# Agent guide for the public Gravitee AutoDeploy core

This repository contains the public/local-first Python core, a same-port React
client, a compatible Tkinter client, and stable boundaries for private corporate
extensions. Read this file and `docs/README.md` before changing the project.

This agent works on the public core. Do not implement a real corporate endpoint,
schema, credential flow or organization-specific form here. `docs/corp/` is a
self-contained consumer handbook that is copied to the private repository; keep
it synchronized when a public extension contract changes, but do not treat its
example package as source code in this repository.

## Non-negotiable architecture

- Python is the only source of business truth. Form fields, defaults,
  visibility, validation, reference resolution, payload construction,
  confirmation, submission and result processing stay server-side.
- React renders API documents and user interactions. Never duplicate a domain
  rule, corporate endpoint, payload builder or validation rule in TypeScript.
- Existing `BaseForm` implementations remain compatible. The web layer projects
  them to JSON through `webapp/form_runtime.py` and invokes their existing hooks.
- Public web core and corporate code are separate deliverables. Never commit
  corporate URLs, schemas, tokens, request examples with personal data, or real
  ITSM/TFS/Gravitee implementations to this repository.
- Corporate forms and services belong in a separate private Python package.
  Connect that package only through `AUTODEPLOY_FORM_REGISTRAR`,
  `AUTODEPLOY_SERVICE_PROVIDER`, `AUTODEPLOY_REFERENCE_HANDLER_FACTORY`,
  `AUTODEPLOY_SEARCH_CATALOG_FACTORY`, `AUTODEPLOY_ENVIRONMENT_HOOK`, and
  `AUTODEPLOY_PLUGIN_REGISTRAR`.
  Keep these boundaries stable.
- Frontend and API are served by one localhost-only Python process on one port.
  The production wheel includes prebuilt `webapp/static`; end users do not need
  Node.js or npm.

## Project map

- `forms/`: public form contracts and examples; no corporate network logic.
- `plugins/`: public contracts for private server-driven custom pages.
- `services/`: public/default service abstractions.
- `handlers/`: reference handlers used by Python forms.
- `webapp/`: FastAPI application, API contracts, form runtime, MCP and AI façade.
- `frontend/`: React + TypeScript source and tests.
- `opencode_integration/`: OpenCode 1.18.18 client, agents and safe sessions.
- `launcher/`: atomic signed/checksummed release delivery.
- `docs/`: current public-core documentation; `docs/README.md` is its router.
- `docs/corp/`: copyable documentation for the private corporate package.

Do not recreate migration diaries, temporary rollout steps or a second general
guide. Document the current target state in the narrowest owning document and
update both sides of a public/private contract when its signature changes.

## Forms and references

Preserve `form_id`, field keys, `FieldType`, `ReferenceConfig`, plural naming and
the existing `BaseForm` lifecycle. Add one-step web actions through
`ServerAction` and interactive field-based actions through `ServerActionDialog`;
a raw Tkinter callback cannot execute in a headless server. Multi-input
references must declare the minimal `ReferenceDependency` allowlist rather than
receiving complete form state.
Reference identifiers come from `value_key`, display text from `label_key`, and
search from `search_keys`. A select returns one identifier; a multiselect returns
an array. Do not load entire large dictionaries into the AI context or browser.
Use the options endpoint and respect Python validation.

Chat `@` references are a cache-only convenience. Use only the API/application
`ReferenceConfig` contracts registered for the global Search page, search only
their declared `search_keys`, and read only the shared `ReferenceCache` snapshot
for the current environment. Never invoke a handler, resolver, HTTP request or
refresh from mention lookup, even
when a cached entry is stale. Re-resolve every client-supplied mention pointer
against that snapshot in Python before adding its authoritative identifier to
the bounded, untrusted AI context.

## Security and configuration

- The web server and managed OpenCode server must bind only to localhost.
- Runtime settings are whitelisted in `webapp/configuration.py`. Secret settings
  are write-only: API responses may expose `configured`, never their values.
- Never log secrets, auth headers, raw `.env`, full ITSM payloads or confidential
  form values. Preserve request-size, Origin, TrustedHost and CSP protections.
- OpenCode runs in an isolated per-user runtime outside the source checkout.
  Agents must not read project files, YAML files or environment dumps.
- AI output never submits a form. Python validation, inline preview and explicit
  human confirmation remain mandatory.

## MCP policy

The optional same-port endpoint is `/api/mcp` and is controlled by
`AUTODEPLOY_MCP_ENABLED`. Tools should be narrowly described, schema-constrained
and safe by default. Most built-in tools are read-only. `prepare_form_draft`
may create idempotent, persistent local state, but it is non-destructive and
cannot preview-submit, deploy or write externally. Manual and AI drafts share
the server-side store until successful submit or explicit deletion. Do not add an autonomous
submit/deploy/write tool without an explicit product decision and a one-time
human confirmation design. Corporate plugin operations are the explicit
exception: each gets a dedicated tool and a fail-closed operator policy
(`deny`, `manual`, `allow`); never expose a wildcard dispatcher. Copilot receives
an exact tool allowlist only when MCP is enabled. Keep external data untrusted.

The web AI topology is documented in `docs/AI_AGENT_ARCHITECTURE.md`. Keep the
main Copilot catalog-free, create the form-search session only on its first MCP
search, reuse it for the life of the Copilot workflow, and force that helper to
the configured `none` thinking variant. Its catalog is routing-only: never add
form fields, schemas or reference values to that session. Repository Researcher
sessions are bounded, read-only and short-lived. New web flows must use Python
drafts rather than adding another model-to-model extractor handoff.

## Development workflow

1. Preserve user changes and inspect the current branch/status first.
2. Use `apply_patch` for source edits.
3. Add or update Python tests for server contracts and Vitest tests for UI logic.
4. Run `python -m compileall`, `pytest`, `npm test`, and `npm run build`.
5. Run Playwright for navigation or interaction changes.
6. Commit the rebuilt `webapp/static` with frontend source changes.
7. Never push major work directly to `master`; use the requested feature branch.

For documentation-only work, at minimum run `python scripts/check_docs.py`,
`git diff --check`, and any focused contract tests whose behavior the
documentation describes.

Build frontend with Node only on the developer/CI machine. Release artifacts are
produced by the pipeline and installed atomically by the Python launcher. Keep
`version.txt` and the corporate update-provider boundary backward compatible.

When a requirement is ambiguous, prefer compatibility, server-side business
logic, least privilege, and explicit human confirmation before side effects.
