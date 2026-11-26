"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..container import Container
from ..core.errors import AppError
from ..settings import Settings
from ..monitoring.prometheus import PrometheusExporter
from .routes import VERSION, router

logger = logging.getLogger("autoremed.api")


def _err(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def create_app(
    container: Container | None = None, settings: Settings | None = None
) -> FastAPI:
    owns_container = container is None
    if container is None:
        settings = settings or Settings.from_env()
        logging.basicConfig(
            level=settings.log_level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        container = Container(settings)
    settings = container.settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container.start()
        yield
        container.shutdown()

    app = FastAPI(
        title="AutoRemed API",
        version=VERSION,
        lifespan=lifespan,
        description="Safe AI-assisted self-healing DevOps prototype. Real-host data is read-only; all "
        "fault injection and remediation operate on an isolated SIMULATION.",
    )
    app.state.container = container
    prometheus_exporter = PrometheusExporter(container)
    app.state.prometheus_exporter = prometheus_exporter

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return Response(
            content=prometheus_exporter.render(),
            media_type=prometheus_exporter.content_type,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _err(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return _err(422, "validation_error", "request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return _err(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error")
        return _err(
            500, "internal_error", "an internal error occurred; see server logs"
        )

    app.include_router(router, prefix="/api")

    dist = settings.frontend_dist
    if os.path.isfile(os.path.join(dist, "index.html")):
        assets = os.path.join(dist, "assets")
        if os.path.isdir(assets):
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return _err(404, "not_found", "no such API route")
            candidate = os.path.join(dist, full_path)
            if (
                full_path
                and os.path.isfile(candidate)
                and os.path.abspath(candidate).startswith(os.path.abspath(dist))
            ):
                return FileResponse(candidate)
            return FileResponse(os.path.join(dist, "index.html"))

    return app
