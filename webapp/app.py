"""FastAPI application factory and bundled React delivery."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core.logging_setup import configure_logging
from webapp import __version__
from webapp.api import router
from webapp.ai_api import router as ai_router
from webapp.ai_service import WebAIService
from webapp.container import ApplicationContainer
from webapp.mcp_server import router as mcp_router
from webapp.settings import WebSettings


_log = logging.getLogger("web.server")


def _secure_response(response, path: str):  # noqa: ANN001
    """Apply the same browser policy to API errors, assets and normal replies."""
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["content-security-policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    if path == "/" or path.endswith("index.html"):
        response.headers["cache-control"] = "no-cache"
    elif path.startswith("/assets/"):
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
    return response


def create_app(
    settings: WebSettings | None = None,
    *,
    container_factory: Callable[[WebSettings], ApplicationContainer] = ApplicationContainer,
) -> FastAPI:
    runtime_settings = settings or WebSettings.load()
    configure_logging(runtime_settings.log_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container_factory(runtime_settings)
        app.state.container.ai = WebAIService(app.state.container)
        _log.info(
            "web server startup host=%s port=%s version=%s",
            runtime_settings.host,
            runtime_settings.port,
            __version__,
        )
        if runtime_settings.auto_connect_opencode:
            app.state.container.opencode_manager.connect_async(
                on_error=lambda exc: _log.warning(
                    "OpenCode auto-connect unavailable error_type=%s", type(exc).__name__
                )
            )
        try:
            yield
        finally:
            app.state.container.ai.close()
            app.state.container.opencode_manager.stop()
            _log.info("web server stopped")

    app = FastAPI(
        title="Gravitee AutoDeploy API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.version = __version__
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def security_and_limits(request: Request, call_next):
        started = time.monotonic()
        request_id = request.headers.get("x-request-id", "")[:100] or uuid.uuid4().hex
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > runtime_settings.max_request_bytes
            except ValueError:
                too_large = True
            if too_large:
                _log.warning(
                    "api request rejected request_id=%s method=%s reason=request_too_large",
                    request_id,
                    request.method,
                )
                response = JSONResponse(
                    status_code=413,
                    content={"error": {"code": "request_too_large", "message": "Request body слишком большой"}},
                    headers={"x-request-id": request_id},
                )
                return _secure_response(response, request.url.path)
        origin = request.headers.get("origin")
        if origin:
            allowed = {
                f"http://127.0.0.1:{runtime_settings.port}",
                f"http://localhost:{runtime_settings.port}",
            }
            # TestClient и reverse local port могут передать текущий Host.
            allowed.add(f"http://{request.headers.get('host', '')}")
            if origin.rstrip("/") not in allowed:
                _log.warning(
                    "api request rejected request_id=%s method=%s reason=origin_rejected",
                    request_id,
                    request.method,
                )
                response = JSONResponse(
                    status_code=403,
                    content={"error": {"code": "origin_rejected", "message": "Недоверенный Origin"}},
                    headers={"x-request-id": request_id},
                )
                return _secure_response(response, request.url.path)

        # Content-Length is only a hint.  Read bounded request streams so a
        # chunked/local API client cannot bypass the configured memory limit.
        if request.method in {"POST", "PUT", "PATCH"}:
            chunks: list[bytes] = []
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > runtime_settings.max_request_bytes:
                    _log.warning(
                        "api request rejected request_id=%s method=%s reason=request_too_large",
                        request_id,
                        request.method,
                    )
                    response = JSONResponse(
                        status_code=413,
                        content={"error": {
                            "code": "request_too_large",
                            "message": "Request body слишком большой",
                        }},
                        headers={"x-request-id": request_id},
                    )
                    return _secure_response(response, request.url.path)
                chunks.append(chunk)
            # Starlette checks this cache before reporting a consumed stream.
            request._body = b"".join(chunks)  # type: ignore[attr-defined]
        try:
            response = await call_next(request)
        except Exception:
            _log.exception(
                "api request crashed request_id=%s method=%s path=%s duration_ms=%d",
                request_id,
                request.method,
                request.url.path[:300],
                int((time.monotonic() - started) * 1000),
            )
            raise
        route = request.scope.get("route")
        route_path = str(getattr(route, "path", request.url.path))[:300]
        duration_ms = int((time.monotonic() - started) * 1000)
        level = (
            logging.WARNING
            if response.status_code >= 400
            else logging.INFO
            if request.method not in {"GET", "HEAD", "OPTIONS"}
            else logging.DEBUG
        )
        _log.log(
            level,
            "api request request_id=%s method=%s route=%s status=%d duration_ms=%d",
            request_id,
            request.method,
            route_path,
            response.status_code,
            duration_ms,
        )
        response.headers["x-request-id"] = request_id
        return _secure_response(response, request.url.path)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "request_validation",
                    "message": "Некорректные параметры запроса",
                    "details": json.loads(json.dumps(exc.errors(), default=str)),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, exc: Exception):
        _log.exception("unhandled API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Внутренняя ошибка сервера. Подробности записаны в лог.",
                }
            },
        )

    app.include_router(router)
    app.include_router(ai_router)
    app.include_router(mcp_router)

    static_dir = runtime_settings.static_dir
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "API endpoint не найден"}})
        index = static_dir / "index.html"
        if not index.is_file():
            return PlainTextResponse(
                "Frontend ещё не собран. Выполните scripts/build_web.py.",
                status_code=503,
            )
        return FileResponse(index)

    return app
