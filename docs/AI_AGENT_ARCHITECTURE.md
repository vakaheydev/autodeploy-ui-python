# AI agent architecture

Status: **implemented for the web Copilot**.

## OpenCode transport

Supported reference versions are **OpenCode 1.18.18 and 2.0.32**.
`connection.py` automatically selects `client.py` for 1.x or `client_v2.py` for
2.x before sending any session mutation. It probes `/api/info` first and falls
back to `/global/health` only for a missing route or the V1 Web UI HTML response.
Authentication, network and server errors never trigger fallback. The selected
adapter stays fixed until reconnect. V2 projects its native `/api` messages into
the same Python agent contract used by V1.

V2 readiness uses `/api/info` followed by bounded polling for required agents,
because the first plugin scan can finish after the HTTP listener starts.
Models and variants come from `/api/model`, providers from `/api/provider`, and
the default from the agent or `/api/model/default`. Disabled models are omitted.

Each V2 session explicitly carries its isolated `location.directory` and native
`permissions` rules (`action`, `resource`, `effect`). Rules deny everything first
and grant only the selected MCP tools. Selected MCP servers are exposed directly
with `codemode: false` in that location; the `execute` tool remains denied.
The shared/global configuration file is never rewritten by this adaptation.

In V2, trusted per-turn instructions use a session instruction entry. Context is
enqueued with `resume: false`; a normal prompt resumes execution. The client
polls the persisted message projection and pending permissions, publishes tool
and text changes through the existing application events, and completes only
after the idle marker following the admitted prompt. Historical idle markers
cannot complete a new turn. Cancellation and timeout interrupt the server loop.
History follows every pagination cursor. Reasoning and raw provider error
bodies are excluded from the projection.

### Native V2 message queue

The web Copilot uses OpenCode's durable inbox, with no AutoDeploy execution
queue. While Copilot is generating, a follow-up is admitted immediately through
`POST /api/session/{id}/prompt` with `delivery: "queue"` and `resume: true`.
OpenCode decides when to deliver it. The UI reads pending user items from
`GET /api/session/{id}/inbox`; removal uses `DELETE .../inbox/{message_id}`.
Deleting an already-delivered item is a native no-op; it does not cancel a turn.

`AUTODEPLOY_OPENCODE_MESSAGE_QUEUE=true` enables admission by default on V2 only.
The setting is editable in Settings → OpenCode and takes effect without restart.
Disabling admission preserves existing native items and still allows their
removal or resumption. The web UI admits at most ten waiting messages. V1 keeps
its single-active-request behavior, including server-side rejection of concurrent
messages. Queue availability is derived from the negotiated adapter.

Model, thinking variant and environment remain fixed during a native batch:
they are session settings in V2. The server rejects changes while running.
Each follow-up carries its own bounded operator prompt, resolved references and
optional ticket context. Display metadata is saved on the native inbox item;
queue API responses never expose the full prepared context. No system/model
configuration is changed during admission. Draft refinement cannot be enqueued.

The adapter observes delivered user boundaries and emits each preceding answer
separately. Draft links and form candidates are derived from that turn's tool
results, avoiding attribution to a later queued turn. Admission and observer
completion are synchronized so an accepted follow-up cannot lose its observer.

Stopping interrupts the native runner and leaves follow-ups in the inbox.
After stop/error the UI shows the pending queue and a resume action. Resumption
re-admits the first existing message ID with `resume: true`; OpenCode's idempotent
admission wakes the queue without duplicating the message. The server observes
execution rather than resending individual requests. Pending items survive a
page refresh and remain in OpenCode across AutoDeploy restarts. The web API
exposes `GET /api/v1/ai/sessions/{id}/queue`, `DELETE .../queue/{message_id}` and
`POST .../queue/resume`, plus `queue` SSE updates and a periodic UI refresh.

V1 retains its existing synchronous message/SSE transport, permission schema,
configured-model discovery and context storage. Both versions keep the same
Python validation, exact MCP allowlists and operator confirmation boundaries.

The optional real-CLI contract test uses local fake provider/MCP endpoints and
does not contact a paid model:

```bash
AUTODEPLOY_TEST_OPENCODE=/path/to/opencode python -m pytest tests/test_opencode_v2_live.py
```

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
|   +-- visible plugin operations       exact allow/ask rules, optional
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

## Exact-form ITSM hook flow

A form can return `ITSMFetchResult.ai(context)` from `fetch_from_itsm`. Unlike a
free chat request, the Python runtime has already selected the form and creates
its persistent pending draft before starting Copilot:

```text
form hook -> sanitized source context -> exact form/draft prompt
          -> get_form_schema (no semantic form search)
          -> prepare_form_draft(existing draft_id)
          -> the same inline field-review and submit lifecycle
```

The generated turn suppresses generic ticket detection, so Copilot never fetches
the same request a second time through `ContextBuilder`. The hook context remains
untrusted data and is not returned to the browser. A typed
`ITSMFetchResult.deterministic(values)` bypasses Copilot and applies the exact
Python-produced patch; legacy mappings retain that deterministic meaning.

Corporate ITSM adapters may also implement the optional
`get_ai_prompt(ITSMAIPromptRequest) -> ITSMAIPrompt | None` capability. Public
core invokes it with already sanitized ticket context and stores the bounded
result in `TRUSTED_ITSM_AI_PROMPT`. This gives the model stable routing and field
mapping rules per corporate request type without promoting ticket prose across
the trust boundary. The returned instructions must be static, reviewed
configuration selected by type; raw ticket fields stay inside `UNTRUSTED`
sections. Adapters without this capability keep the default Copilot behavior.
An operator can override the instructions for an exact returned `ticket_type`
under **Settings → ITSM and AI**. These typed server-side rules are read for
each newly loaded ticket, take precedence over the hook's fallback prompt, and
never replace the corporate adapter's responsibility to identify the type.

For ordinary conversation Copilot answers without loading the form catalog or
calling form/repository tools. A request can create more than one draft; the
chat returns a link for every form and labels the outcome as an execution plan.

## Operator @ references

Typing `@` in the web composer opens a cross-catalog picker for the current
environment. `POST /api/v1/ai/reference-mentions/search` reads only persistent
`ReferenceCache` snapshots for the API/application catalogs configured for the
global Search page. Form-field and plugin-field references are intentionally not
included, so the same API is not repeated for every form that uses it. Mention
lookup never calls a resolver, performs HTTP, refreshes a resource or applies
TTL; an expired entry remains selectable until an explicit application action
replaces or invalidates it. Search uses each Search-page
`ReferenceConfig.search_keys` in declaration order.

The visible message contains the selected label and identifier. The client also
sends a narrow catalog/cache/identifier pointer, which Python resolves against
the cache again before starting OpenCode. The model receives the authoritative
selected ID plus bounded non-secret label/search fields in a separate untrusted
data section. It is instructed not to spend a repository call rediscovering the
same entity. A pointer that disappeared after selection is rejected before the
turn starts; it is never silently guessed or refreshed.

Gravitee entity/reference IDs are strictly environment-local. Even when an API,
application, subscription or plan represents the same logical object in two
environments, its IDs are guaranteed to differ. Copilot may reuse an `@` ID only
in the environment recorded with that mention; after an environment switch it
must resolve the target entity again by stable semantic facts such as
`context_path` or name. This restriction does not apply to AutoDeploy `form_id`
or `workflow_id` values.

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
- expands an array-valued repeated block into canonical `block`, `block_2`,
  `block_3` instances and normalizes `block[0]`/`block.0` leaf notation;
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

## Chat transcript and session metadata

OpenCode remains the persistent source of the conversation. During a live turn,
text emitted before another tool call is published as an `assistant_note` SSE
event in its original position; the text after the final tool is the single
final `assistant` event. Restoring a session rebuilds the same interleaved
timeline from OpenCode message parts instead of grouping all tools before all
text. OpenCode `reasoning` parts, ignored text parts and text explicitly marked
as an analysis/reasoning channel are never published to the browser. This keeps
intermediate messages visible without exposing model chain-of-thought.

The session snapshot owns `generation_started_at`, so refreshing the browser
continues the existing elapsed-time counter. The header shows the last assistant
message's context usage against `limit.context` for the selected model; both
values come from OpenCode, not a browser estimate. OpenCode's generated session
title is used when available, with a short local fallback. `PATCH
/api/v1/ai/sessions/{session_id}` renames both the AutoDeploy chat and its
OpenCode session.

## Trust and permission boundaries

- ITSM, ADO, operator text, diagnostics, repository definitions and MCP output
  are untrusted data.
- All agent files deny files, shell, edit, web, skills and subagents by default.
- Main Copilot gets only the exact configured MCP allowlists.
- Corporate plugins are invisible by default. Each visible plugin operation has
  an independent `deny`, `manual` or `allow` policy. `manual` maps to OpenCode
  `ask` on every invocation; MCP dispatch rechecks a later `deny` even for a
  stale session.
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

Corporate custom pages use a separate `AUTODEPLOY_PLUGIN_REGISTRAR` and do not
enter form routing. They share form field/reference contracts, receive private
services server-side and expose operations only through the operator-controlled
plugin policy. Authoring details are in [corp/PLUGINS.md](corp/PLUGINS.md).

## Compatibility and removal plan

`FormExtractorAgent`, `form-extractor.md`, router code and legacy extraction
endpoints are retained to keep the desktop client and old capabilities working.
They are not part of the new web flow. Remove them only after the desktop path
is migrated to the same draft API and stored legacy handoffs are no longer a
supported compatibility requirement.
