# Installation, build and delivery

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

Only `TFS_TOKEN` is edited by the launcher. Administrators/users add other server
secrets directly to `config/.env`; updates preserve this file and never move it
inside a version directory. Start later with `Gravitee AutoDeploy.cmd`.

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
