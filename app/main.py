"""FastAPI application entrypoint.

On startup: configure logging, build the DI container, create database tables,
and start the hourly monitoring scheduler. On shutdown: stop the scheduler.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.containers import Container
from app.core.exceptions import (
    AppError,
    ConfigurationError,
    NotFoundError,
    ProviderError,
)
from app.database.session import init_db
from app.logging_config import configure_logging
from app.scheduler import MonitoringScheduler

logger = logging.getLogger("main")


def _status_for(exc: AppError) -> int:
    """Map a domain exception to an HTTP status code."""
    if isinstance(exc, ConfigurationError):
        return 400  # bad/missing configuration in the request's reach
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ProviderError):
        return 502  # upstream provider (Gemini/Pexo/TikTok) failed
    return 500


def _register_exception_handlers(app: FastAPI) -> None:
    """Ensure every error becomes a clean JSON response, never a raw 500 trace."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        status = _status_for(exc)
        logger.warning(
            "%s on %s -> HTTP %d: %s",
            type(exc).__name__,
            request.url.path,
            status,
            exc,
        )
        return JSONResponse(
            status_code=status,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Full traceback is logged server-side; the client gets a safe message.
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "detail": "An unexpected error occurred. Check server logs.",
            },
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.container.settings()
    configure_logging(settings.log_level)
    logger.info(
        "Starting %s | script=%s video=%s ads=%s",
        settings.app_name,
        settings.script_provider,
        settings.video_provider,
        settings.ad_platform,
    )

    # Create tables (SQLite by default; Postgres if DATABASE_URL points there).
    init_db(app.state.container.engine())

    # Start hourly monitoring + auto-pause.
    scheduler = MonitoringScheduler(
        app.state.container.monitoring_service(),
        interval_hours=settings.monitor_interval_hours,
    )
    scheduler.start()
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        scheduler.shutdown()


def create_app() -> FastAPI:
    container = Container()
    # Configure logging early so container construction is logged too.
    configure_logging(container.settings().log_level)

    app = FastAPI(
        title="TikTok Ad Creative Automation",
        version="1.0.0",
        description=(
            "Generates ad scripts and videos, deploys them as TikTok ads inside "
            "an existing ad group, and auto-pauses underperformers."
        ),
        lifespan=lifespan,
    )
    app.state.container = container
    app.include_router(router)
    _register_exception_handlers(app)

    # Serve downloaded videos so the dashboard can preview/download them.
    storage_dir = container.settings().video_storage_dir
    os.makedirs(storage_dir, exist_ok=True)
    app.mount("/videos", StaticFiles(directory=storage_dir), name="videos")

    return app


app = create_app()
