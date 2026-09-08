"""HTTP and SSE endpoints for the web AI experience."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import Field

from webapp.models import (
    ChatMessageRequest,
    ChatReferenceSearchRequest,
    ChatSessionRequest,
    ChatSessionUpdateRequest,
    PermissionReplyRequest,
    StrictModel,
)


router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


class ExtractionRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    current_values: dict[str, Any] = Field(default_factory=dict)


class RefineRequest(StrictModel):
    guidance: str = Field(min_length=1, max_length=20_000)


class DraftRefineRequest(RefineRequest):
    current_values: dict[str, Any] = Field(default_factory=dict)
    pending_fields: list[str] = Field(default_factory=list, max_length=100)


def service(request: Request):
    return request.app.state.container.ai


def translate(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, (ValueError, RuntimeError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.post("/reference-mentions/search")
def search_reference_mentions(
    body: ChatReferenceSearchRequest,
    request: Request,
):
    """Search the current environment's existing cache without refreshing it."""
    try:
        return service(request).search_reference_mentions(
            environment=body.environment,
            query=body.query,
            limit=body.limit,
        )
    except Exception as exc:
        translate(exc)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(_body: ChatSessionRequest, request: Request):
    try:
        return service(request).create_session()
    except Exception as exc:
        translate(exc)


@router.get("/sessions")
def list_sessions(request: Request):
    return service(request).list_sessions()


@router.get("/sessions/{session_id}")
def session(session_id: str, request: Request):
    try:
        return service(request).snapshot(session_id, include_events=True)
    except Exception as exc:
        translate(exc)


@router.patch("/sessions/{session_id}")
def rename_session(
    session_id: str, body: ChatSessionUpdateRequest, request: Request
):
    try:
        return service(request).rename(session_id, body.title)
    except Exception as exc:
        translate(exc)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, request: Request):
    service(request).delete(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
def message(session_id: str, body: ChatMessageRequest, request: Request):
    try:
        return service(request).start_message(
            session_id,
            message=body.message,
            environment=body.environment,
            ticket_id=body.ticket_id,
            provider_id=body.provider_id,
            model_id=body.model_id,
            thinking=body.thinking,
            mentions=[item.model_dump() for item in body.mentions],
        )
    except Exception as exc:
        translate(exc)


@router.post("/sessions/{session_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel(session_id: str, request: Request):
    try:
        service(request).cancel(session_id)
        return {"accepted": True}
    except Exception as exc:
        translate(exc)


@router.post("/sessions/{session_id}/permissions/{permission_id}")
def permission(
    session_id: str, permission_id: str, body: PermissionReplyRequest, request: Request
):
    try:
        service(request).permission(session_id, permission_id, body.allow)
        return {"accepted": True}
    except Exception as exc:
        translate(exc)


@router.get("/sessions/{session_id}/events")
async def events(
    session_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
):
    try:
        service(request).snapshot(session_id, include_events=False)
    except Exception as exc:
        translate(exc)

    last_event_id = request.headers.get("last-event-id", "").strip()
    try:
        resume_after = max(after, int(last_event_id)) if last_event_id else after
    except ValueError:
        resume_after = after

    async def stream():
        sequence = resume_after
        while True:
            if await request.is_disconnected():
                return
            batch = await asyncio.to_thread(
                service(request).events_after, session_id, sequence, 15.0
            )
            if not batch:
                yield ": keepalive\n\n"
                continue
            for event in batch:
                sequence = max(sequence, event.sequence)
                payload = json.dumps(
                    {
                        "sequence": event.sequence,
                        "kind": event.kind,
                        "timestamp": event.timestamp,
                        "payload": event.payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"id: {event.sequence}\ndata: {payload}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "x-accel-buffering": "no",
            "connection": "keep-alive",
        },
    )


@router.post("/handoffs/{token}/extract", status_code=status.HTTP_202_ACCEPTED)
def extract(token: str, body: ExtractionRequest, request: Request):
    try:
        return service(request).start_extraction(
            token, body.environment, body.current_values
        )
    except Exception as exc:
        translate(exc)


@router.get("/extractions/{job_id}")
def extraction(job_id: str, request: Request):
    try:
        return service(request).extraction(job_id)
    except Exception as exc:
        translate(exc)


@router.post("/extractions/{job_id}/refine", status_code=status.HTTP_202_ACCEPTED)
def refine(job_id: str, body: RefineRequest, request: Request):
    try:
        return service(request).refine_extraction(job_id, body.guidance)
    except Exception as exc:
        translate(exc)


@router.delete("/extractions/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def close_extraction(
    job_id: str, request: Request, cancel: bool = Query(default=False)
):
    try:
        service(request).close_extraction(job_id, cancel=cancel)
    except Exception as exc:
        translate(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/drafts/{draft_id}")
def draft(draft_id: str, request: Request):
    try:
        return service(request).draft(draft_id)
    except Exception as exc:
        translate(exc)


@router.post("/drafts/{draft_id}/refine", status_code=status.HTTP_202_ACCEPTED)
def refine_draft(
    draft_id: str,
    body: DraftRefineRequest,
    request: Request,
):
    try:
        return service(request).refine_draft(
            draft_id,
            guidance=body.guidance,
            current_values=body.current_values,
            pending_fields=body.pending_fields,
        )
    except Exception as exc:
        translate(exc)


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(draft_id: str, request: Request):
    try:
        service(request).delete_draft(draft_id)
    except Exception as exc:
        translate(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
