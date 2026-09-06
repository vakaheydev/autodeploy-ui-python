"""Versioned REST API.  All domain decisions remain in Python."""
from __future__ import annotations

import dataclasses
import os
import string
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from config.categories import CATEGORIES, CATEGORY_ORDER
from config.environments import ENVIRONMENTS
from forms.registry import FormRegistry
from webapp.form_runtime import FormNotFoundError, FormVersionConflict, form_version
from webapp.models import (
    ActionRequest,
    ReferenceRequest,
    SearchRequest,
    SettingsUpdateRequest,
    SubmitRequest,
    TicketRequest,
    ValuesRequest,
)
from webapp.configuration import settings_snapshot, update_settings


router = APIRouter(prefix="/api/v1")


def container(request: Request):
    return request.app.state.container


def _raise_runtime_error(exc: Exception) -> None:
    if isinstance(exc, FormNotFoundError):
        raise HTTPException(status_code=404, detail="Объект не найден") from exc
    if isinstance(exc, FormVersionConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("/health", tags=["system"])
def health(request: Request) -> dict[str, Any]:
    app_container = container(request)
    return {
        "healthy": True,
        "service": "gravitee-autodeploy-web",
        "version": request.app.version,
        "forms": len(FormRegistry().all_forms()),
        "opencode": app_container.opencode_manager.status.state,
        "mcp": "enabled" if app_container.settings.mcp_enabled else "disabled",
    }


@router.get("/settings", tags=["settings"])
def settings(request: Request):
    return settings_snapshot(container(request).env_manager)


@router.put("/settings", tags=["settings"])
def save_settings(body: SettingsUpdateRequest, request: Request):
    app_container = container(request)
    try:
        return update_settings(
            app_container.env_manager,
            app_container.opencode_manager,
            body.values,
            body.clear,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/settings/filesystem", tags=["settings"])
def settings_filesystem(
    path: str = Query(default="", max_length=4096),
):
    """List local paths for the settings picker without reading file contents."""
    try:
        current = Path(path).expanduser() if path.strip() else Path.cwd()
        if not current.exists():
            current = Path.cwd()
        current = current.resolve(strict=True)
        if not current.is_dir():
            current = current.parent
        children = sorted(
            current.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.casefold()),
        )[:2000]
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=f"Не удалось открыть папку: {exc}") from exc
    roots: list[str]
    if os.name == "nt":
        roots = [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]
    else:
        roots = ["/"]
    entries = []
    for item in children:
        try:
            is_dir = item.is_dir()
            is_file = item.is_file()
        except OSError:
            continue
        entries.append({
            "name": item.name,
            "path": str(item),
            "is_dir": is_dir,
            "is_file": is_file,
        })
    parent = str(current.parent) if current.parent != current else ""
    return {"current": str(current), "parent": parent, "roots": roots, "entries": entries}


@router.get("/catalog", tags=["forms"])
def catalog(request: Request) -> dict[str, Any]:
    app_container = container(request)
    categories = [
        {
            "id": key,
            "label": CATEGORIES.get(key, key),
            "forms": app_container.forms.list_forms(key),
        }
        for key in CATEGORY_ORDER
    ]
    return {
        "categories": categories,
        "environments": [dataclasses.asdict(value) for value in ENVIRONMENTS],
    }


@router.get("/forms", tags=["forms"])
def forms(request: Request, category: str = Query(default="", max_length=80)):
    return {"items": container(request).forms.list_forms(category)}


@router.get("/forms/{form_id}", tags=["forms"])
def form_document(
    form_id: str,
    request: Request,
    environment: str = Query(default="test_int", max_length=80),
):
    try:
        return container(request).forms.describe(form_id, environment)
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/forms/{form_id}/state", tags=["forms"])
def form_state(form_id: str, body: ValuesRequest, request: Request):
    try:
        return container(request).forms.state(
            form_id, body.environment, body.values, body.form_version
        )
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/forms/{form_id}/validate", tags=["forms"])
def validate_form(form_id: str, body: ValuesRequest, request: Request):
    try:
        result = container(request).forms.validate(
            form_id, body.environment, body.values, body.form_version
        )
        return dataclasses.asdict(result)
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/forms/{form_id}/preview", tags=["forms"])
def preview_form(form_id: str, body: ValuesRequest, request: Request):
    try:
        return container(request).forms.preview(
            form_id, body.environment, body.values, body.form_version
        )
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/forms/{form_id}/submit", tags=["forms"])
def submit_form(form_id: str, body: SubmitRequest, request: Request):
    try:
        result = container(request).forms.submit(
            form_id,
            body.environment,
            body.values,
            body.form_version,
            body.confirmation_token,
        )
    except Exception as exc:
        _raise_runtime_error(exc)
    if not result.get("success"):
        code = result.get("code")
        status_code = 409 if code == "confirmation_required" else 422
        raise HTTPException(status_code=status_code, detail=result)
    return result


@router.post("/forms/{form_id}/actions/{action_id}", tags=["forms"])
def run_form_action(
    form_id: str, action_id: str, body: ActionRequest, request: Request
):
    try:
        return container(request).forms.run_action(
            form_id,
            action_id,
            body.environment,
            body.values,
            body.form_version,
            body.confirmation_token,
        )
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/forms/{form_id}/fields/{field_path:path}/options", tags=["references"])
def reference_options(
    form_id: str, field_path: str, body: ReferenceRequest, request: Request
):
    try:
        return container(request).forms.options(
            form_id,
            field_path,
            body.environment,
            body.values,
            body.query,
            body.offset,
            body.limit,
            body.refresh,
        )
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/forms/{form_id}/ticket", tags=["forms"])
def fetch_ticket(form_id: str, body: TicketRequest, request: Request):
    try:
        return container(request).forms.fetch_ticket(
            form_id, body.environment, body.ticket_id
        )
    except Exception as exc:
        _raise_runtime_error(exc)


@router.get("/runs", tags=["runs"])
def runs(request: Request):
    result = []
    for record in container(request).run_storage.load_all():
        current = None
        try:
            form = FormRegistry().get(record.form_id)
            current = {field.key: field.field_type.value for field in form.fields}
        except KeyError:
            pass
        item = dataclasses.asdict(record)
        item["stale"] = current is None or current != record.fields_snapshot
        result.append(item)
    return {"items": result}


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["runs"])
def delete_run(run_id: str, request: Request) -> Response:
    container(request).run_storage.delete(run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/search", tags=["search"])
def search(body: SearchRequest, request: Request):
    try:
        return container(request).forms.search(
            body.kind, body.environments, body.query, body.limit, body.refresh
        )
    except Exception as exc:
        _raise_runtime_error(exc)


@router.post("/submissions/{submission_id}/poll", tags=["submissions"])
def poll_submission(submission_id: str, request: Request):
    try:
        return container(request).forms.poll(submission_id)
    except Exception as exc:
        _raise_runtime_error(exc)


@router.get("/opencode/status", tags=["opencode"])
def opencode_status(request: Request):
    return dataclasses.asdict(container(request).opencode_manager.status)


@router.post("/opencode/{action}", tags=["opencode"])
def opencode_action(action: str, request: Request):
    manager = container(request).opencode_manager
    try:
        if action == "connect":
            manager.connect()
        elif action == "create":
            manager.create()
        elif action == "check":
            manager.check_status()
        elif action == "restart":
            manager.restart()
        elif action in {"stop", "disconnect"}:
            manager.disconnect()
        else:
            raise HTTPException(status_code=404, detail="Неизвестное действие")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return dataclasses.asdict(manager.status)


@router.get("/opencode/models", tags=["opencode"])
def opencode_models(request: Request):
    client = container(request).opencode_manager.client
    if client is None:
        raise HTTPException(status_code=503, detail="OpenCode не подключён")
    try:
        catalog = client.configured_model_catalog(agent_name="autodeploy-copilot")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "items": [dataclasses.asdict(item) for item in catalog.models],
        "default": dataclasses.asdict(catalog.default) if catalog.default else None,
    }


@router.get("/opencode/mcp", tags=["opencode"])
def opencode_mcp(request: Request):
    client = container(request).opencode_manager.client
    if client is None:
        return {"connected": False, "items": []}
    try:
        servers = client.list_mcp_servers()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "connected": True,
        "items": [
            {
                "name": name,
                "status": str(value.get("status") or "unknown"),
                "error": str(value.get("error") or ""),
            }
            for name, value in sorted(servers.items())
        ],
    }
