# Installation, build and delivery

Целевой private-package contract и сборка корпоративного wheel описаны в
[corp/](corp/README.md). Этот документ относится к public launcher и delivery
mechanism.

## User installation (no Node/npm)

The release pipeline produces `gravitee-autodeploy-installer-X.Y.Z.zip`.

1. Extract it to any temporary directory.
2. Run `install.cmd` on Windows (or `python install.py`).
3. Enter the TFS token in the masked launcher field.
4. Click **Установить пакет**, then **Запустить**.

The launcher uses the user's existing Python only to create an isolated virtual
environment. All Python wheels and the compiled React application are inside the
release archive; installation does not contact PyPI or npm.

Default Windows location:

```text
%LOCALAPPDATA%\GraviteeAutoDeploy\
  Gravitee AutoDeploy.cmd
  launcher\
  config\.env
  data\
  logs\
  downloads\
  versions\1.0.0\.venv\
  current.json
```

Only `TFS_TOKEN` is edited by the launcher. Other whitelisted settings can be
edited on the local **Настройки** page or directly in `config/.env`; updates
preserve this file and never move it inside a version directory. Stored secrets
are write-only in the browser API: the page can replace or explicitly clear
them, but cannot read their current value. Start later with
`Gravitee AutoDeploy.cmd`.

The optional AutoDeploy MCP is disabled by default. Set
`AUTODEPLOY_MCP_ENABLED=true` and restart to expose `/api/mcp`; see
[MCP.md](MCP.md).

## OpenCode 1.18.18 / 2.0.32

Install OpenCode separately and make `opencode` available on `PATH`. For an npm
installation the V2 package is `@opencode/cli@2.0.32`; the supported V1 package
is `opencode-ai@1.18.18`. The AutoDeploy release
does not bundle the CLI. Verify it with `opencode --version`.

**Создать сервер** starts `opencode serve --hostname 127.0.0.1 --port <free-port>`
in the isolated runtime. The CLI version determines its launch configuration;
connections automatically select the V1 or V2 adapter from the server's reported
version. V2 requires authentication: AutoDeploy uses the saved
server password or generates an in-memory password for its owned process.
The V2 username is `opencode`. Shell password aliases cannot override it.
V1 preserves optional Basic Auth and the configured username.

For **Подключиться**, start a V2 server with a known `OPENCODE_PASSWORD`, then
save the same password and its localhost address in AutoDeploy settings.
If OpenCode returns HTTP 401, AutoDeploy opens a dismissible password dialog.
The login form also remains in **Настройки → OpenCode** until authentication
succeeds. Closing the dialog does not hide that settings form or reopen the
dialog on every status refresh. **Сохранить и подключиться** saves the password
as a write-only local setting and checks the current server without restarting
it. A rejected password leaves the form available for another attempt.
`OPENCODE_SERVER_PASSWORD` remains an upstream alias. Opening the separate
OpenCode Web UI requires its own login; set a known password before creating
the server if you need that UI. Passwords are never included in session links.

Existing provider/agent configuration is normalized by OpenCode V2. AutoDeploy
uses the native API for V2 and native `mcp.servers.autodeploy` configuration with
`disabled: false`, `codemode: false` and `oauth: false`. Other MCP entries are
preserved. V1 receives the original `mcp.autodeploy` entry with `enabled: true`.
The managed entry is switched when connecting to a different version; provider
configuration for each version remains owned by OpenCode/the operator.
See [AI_AGENT_ARCHITECTURE.md](AI_AGENT_ARCHITECTURE.md) for transport
and session policy details.

In **Settings → OpenCode**, **Очередь сообщений Copilot** controls native V2
follow-ups (`AUTODEPLOY_OPENCODE_MESSAGE_QUEUE`, default `true`). It applies
without restarting. OpenCode 1.x continues to accept one request at a time.
While an answer is running, Enter adds a follow-up to the native OpenCode inbox;
the queue panel supports removal and resuming after interruption. The queued
batch shares the current model, thinking variant and environment.

Logs:

- launcher/update: `logs/launcher.log`;
- Python API, forms and OpenCode integration: `logs/autodeploy.log` plus rotated
  `autodeploy.log.1` ... `.5`;
- OpenCode's own upstream log remains in its normal OpenCode data directory.

## Update protocol

The launcher checks a small JSON manifest from TFS on each normal launch. The URL
is set in the corporate-only `launcher/corporate_update.py` or, for local testing,
with `AUTODEPLOY_UPDATE_MANIFEST_URL` in `.env`.

```json
{
  "schema_version": 1,
  "version": "1.1.0",
  "artifact_url": "https://tfs.example/.../gravitee-autodeploy-app-1.1.0.zip",
  "sha256": "64 lowercase hex characters",
  "size": 12345678,
  "changelog": "Text shown before approval",
  "minimum_launcher_version": "1.0.0"
}
```

The TFS token is sent as Basic PAT auth. Authorization is removed if TFS redirects
to another host. The launcher downloads to `.part`, verifies size and SHA-256,
rejects zip-slip/symlinks, stages the inert release payload, creates the virtual
environment at its final version path, installs only from the bundled wheelhouse,
smoke-tests the installed package from outside the source tree, and only then
atomically changes `current.json`. A failed install restores the previous files;
the previous activated version remains available:

```powershell
python -m launcher rollback
```

If a newly activated server fails its 30-second health check, normal launch
automatically rolls back once.

## Developer run

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cd frontend && npm ci && npm test && npm run build && cd ..
AUTODEPLOY_OPENCODE_AUTO_CONNECT=false .venv/bin/python -m webapp
```

The UI and API are then on `http://127.0.0.1:8765`; API docs are at
`http://127.0.0.1:8765/api/docs`.

## Production build

Node is a build-agent dependency only. Run on the same OS/Python family as target
users so binary wheels (notably Pydantic Core) match:

```bash
python scripts/build_release.py \
  --artifact-url "https://tfs.example/path/gravitee-autodeploy-app-1.0.0.zip" \
  --extra-wheel path/to/corp_autodeploy-1.0.0-py3-none-any.whl
```

The checked-in Windows pipeline downloads compatible binary wheels for CPython
3.10, 3.11, 3.12 and 3.13. For a manual Windows build use the same flags:

```text
--wheel-platform win_amd64 --python-version 310 --python-version 311 \
--python-version 312 --python-version 313
```

The release records its supported Python versions and target platform. The
installer checks both before creating a virtual environment.

Outputs in `build/release/`:

- immutable app bundle used by updater;
- bootstrap installer bundle for first installation;
- `update-manifest.json` to publish only after the app archive is uploaded.

Publish the immutable archive first, verify its SHA, then replace the manifest as
the final atomic release step. Never rebuild an already published SemVer.

`azure-pipelines.yml` performs npm clean install/audit, React unit tests, Python
tests, a production build, Chromium Playwright tests and release packaging. A
corporate pipeline can inject its extension wheel and final artifact URL without
changing public server code.

Before publishing, the produced application archive can also be installed and
started in an isolated temporary directory with:

```bash
python scripts/verify_release.py build/release/gravitee-autodeploy-app-1.0.0.zip
```

This verifies the per-version virtual environment, health endpoint, bundled SPA
assets and a real Python form preview through HTTP.
