# AI agent architecture

Status: **implemented for the web Copilot**.

## Decision

The web assistant uses one conversational orchestrator and two isolated helper
sessions:

1. `autodeploy-copilot` is the long-lived conversation and the only component
   that talks to the operator. It decides whether tools are needed and creates
   Python-validated form drafts through AutoDeploy MCP.
2. `form-search` is a tool-free, long-lived semantic index owned by the same web
   workflow. It is created lazily on the first form-related request, receives a
   routing-only catalog once and always runs with the exact `none` thinking
   variant. The catalog contains form identity plus `purpose`, `use_when` and
   `avoid_when`, but no fields, schemas or reference values. Later searches
   reuse this session.
3. `repository-researcher` is a short-lived optional worker for a genuinely
   complex JSON Repository investigation. It receives one bounded question,
   can call only the approved read-only repository tools and is deleted after
   returning evidence to Copilot.

The web path has no AI-to-AI `form-extractor` handoff. The old extractor files
and REST handoff endpoints remain temporarily for the Tkinter client and old
saved web links, but new web Copilot turns do not invoke them.

If `AUTODEPLOY_MCP_ENABLED=false`, the same main session can still converse and
use separately configured repository reads, but form discovery/draft creation is
unavailable. The context tells Copilot to explain that setting instead of
guessing a form. If MCP is enabled but OpenCode did not connect the `autodeploy`
entry, the first turn fails early with an actionable connection error.

OpenCode responses from the main Copilot are ordinary Markdown. Structured
application state crosses the main Copilot boundary through narrow MCP tool
arguments. Python, not a model response, resolves references, validates fields
and owns the draft. The main Copilot therefore never uses OpenCode
`StructuredOutput`. The internal form-search helper uses one deliberately tiny,
stable schema containing only `form_id`, `score` and `reason`; it does not embed
the catalog or a form-ID enum in every request, and Python filters unknown IDs.

## Session topology

```text
web workflow (opaque workflow_id)
|
+-- main Copilot session                created on first chat message
|   +-- conversation history            retained across turns
|   +-- AutoDeploy MCP                  exact allowlist
|   +-- JSON Repository MCP             exact read-only allowlist
|   `-- complete form catalog           NOT present
|
+-- semantic form-search session        created on first semantic_search_forms
|   +-- routing-only trusted catalog    stored once with noReply
|   +-- fields/schemas/references        NOT present
|   +-- thinking                         none
|   +-- MCP/files/shell/web             unavailable
|   `-- reused until main workflow closes
|
`-- repository-researcher session       created only for one complex question
    +-- bounded question/evidence scope
    +-- JSON Repository MCP             read-only tools only
    +-- git_pull                         denied
    `-- deleted immediately after result/cancellation
```

Creating a chat does not build, serialize or send the form catalog. Greetings
therefore initialize only the small Copilot context. The first
`semantic_search_forms` call builds the compact catalog from registered forms and
their explicit routing configuration, starts `form-search`, stores it once, and
returns authoritative routing entries enriched with model-produced score/reason.
Only after Copilot selects a candidate does it request that one form's live
schema. A second search uses the same session and sends only the new query.

Both the main and form-search sessions are cancelled together and deleted when
the web workflow is deleted. Researcher cancellation is also connected to the
same operation cancel event.

## Simple form flow

```text
operator message
    -> Copilot decides that a form may be required
    -> autodeploy_semantic_search_forms(workflow_id, query)
       -> persistent none-thinking form-search session
    -> autodeploy_get_form_schema(form_id, environment)
    -> inline options or autodeploy_search_reference_options when needed
    -> optional autodeploy_calculate_form_state
    -> autodeploy_prepare_form_draft(... field proposals ...)
       -> Python field-path/type checks
       -> Python reference label-to-ID resolution
       -> Python dynamic state and domain validation
       -> persistent local draft_id; no submission
    -> normal Markdown answer + draft link in chat
    -> proposed values are rendered directly in the live web form
    -> operator accepts/rejects each value or all values
    -> normal preview and explicit submit confirmation
    -> existing Python form lifecycle
```

For ordinary conversation Copilot answers without loading the form catalog or
calling form/repository tools. A request can create more than one draft; the
chat returns a link for every form and labels the outcome as an execution plan.

## Complex repository flow

```text
Copilot identifies one concrete missing fact
    -> autodeploy_research_repository(workflow_id, question, scope, facts, depth)
    -> isolated Researcher session
    -> targeted read-only JSON Repository MCP calls
    -> concise evidenced report returned to the waiting Copilot tool call
    -> Researcher session deleted
    -> Copilot continues and prepares a draft when possible
```

Researcher is intended for multi-file correlation, version comparison, conflict
investigation and reconstruction from several repository entities. It must not
be used for form discovery, SELECT/MULTISELECT dictionaries, ordinary validation
or facts already supplied by the operator. Simple entity lookup stays a direct
Copilot call to an allowed repository tool.

`focused` research prefers `low`; `deep` prefers `xhigh`, with an explicit
fallback to an available configured variant. Form search never falls back: the
selected model must expose `none` in `opencode.json`.

## Draft contract and review boundary

`prepare_form_draft` accepts an opaque workflow ID, form ID, environment, live
form version and one or more proposals with exact field path, value, confidence
and source. It:

- rejects stale forms, unknown paths/properties and invalid confidence values;
- distinguishes SELECT scalars from MULTISELECT arrays through the Python form;
- resolves semantic labels against the authoritative reference handler and
  stores only accepted identifiers;
- evaluates dependencies and form-specific validation;
- records warnings, conflicts, candidates and field-level provenance;
- is content-addressed so an OpenCode retry returns the same draft;
- never calls preview submission, submit, deployment or an external write.

Drafts are written atomically to the server's per-user data directory. Manual
edits and AI proposals use the same representation. They survive browser,
server and OpenCode restarts and are removed only after successful submission
or explicit operator deletion.
Refinement reuses the same draft and main Copilot conversation. The visible form
values and still-pending review fields are sent back; accepted/manual values are
preserved and a failed refinement leaves the previous proposal set intact.

The browser cannot submit a draft. It can only load proposed values into the
normal form renderer. Each green check keeps the currently visible value (so a
manual edit is respected); each red cross restores that field's baseline.
After review, the ordinary Python validate/preview/confirmation/submit path is
still mandatory.

## Trust and permission boundaries

- ITSM, ADO, operator text, diagnostics, repository definitions and MCP output
  are untrusted data.
- All agent files deny files, shell, edit, web, skills and subagents by default.
- Main Copilot gets only the exact configured MCP allowlists.
- JSON Repository read tools can run without approval; their calls remain
  visible. Main-session `git_pull` is `ask` per invocation when enabled.
- Form search gets no tools. Researcher gets repository reads only and cannot
  call `git_pull` or AutoDeploy MCP.
- Form and reference truth remains in Python. No AI tool can submit a form.

## Public/private extension rule

Corporate forms and services stay in a separately installed private package.
Its registrar must register a `FormRoutingDescription` for every form. Lazy
catalog creation means a missing description affects form search when first
used, not ordinary chat startup. The copyable corporate agent handbook is in
[corp/](corp/README.md).

## Compatibility and removal plan

`FormExtractorAgent`, `form-extractor.md`, router code and legacy extraction
endpoints are retained to keep the desktop client and old capabilities working.
They are not part of the new web flow. Remove them only after the desktop path
is migrated to the same draft API and stored legacy handoffs are no longer a
supported compatibility requirement.
