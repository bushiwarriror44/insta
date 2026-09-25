"""FastAPI entrypoint for the admin web UI."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.deps import AuthPrincipal, DocsOwnerDep
from app.api.routes import (
    accounts,
    admin_notes,
    assistant,
    auth,
    browser,
    dashboard,
    diagnostics,
    events,
    factory,
    gpu,
    health,
    jobs,
    maintenance,
    operators,
    panel,
    proxies,
    publications,
    screenshots,
    settings as settings_routes,
    videos,
    worker,
)
from app.config import settings
from app.db import SessionLocal, init_db
from app.logging_setup import configure_logging, get_logger
from app.panel.settings_store import auth_is_required, get_or_create_panel_settings
from app.scheduler.heartbeat import worker_status
from app.services import ollama_control, salad_idle, worker_control

logger = get_logger(__name__)


def _maybe_start_ollama() -> None:
    if not settings.ollama_autostart:
        return
    try:
        status = ollama_control.ensure_started(pull=False)
        logger.info(
            "api.ollama",
            reachable=status.reachable,
            model_ready=status.model_ready,
            detail=status.detail or None,
        )
        if status.reachable and not status.model_ready:
            ollama_control.pull_in_background()
    except ollama_control.OllamaProblem as exc:
        logger.warning("api.ollama_failed", error=str(exc))


def _maybe_start_worker() -> None:
    if not settings.worker_autostart:
        return
    db = SessionLocal()
    try:
        beat = worker_status(db)
        heartbeat_alive = beat.known and not beat.stale
        started = worker_control.ensure_started(heartbeat_alive=heartbeat_alive)
        if started and started.alive:
            logger.info("api.worker_autostart", pid=started.pid)
        elif heartbeat_alive:
            logger.info("api.worker_already_running")
    except worker_control.WorkerProblem as exc:
        logger.warning("api.worker_autostart_failed", error=str(exc))
    finally:
        db.close()


async def _salad_idle_loop() -> None:
    while True:
        await asyncio.sleep(salad_idle.POLL_SECONDS)
        try:
            await asyncio.to_thread(salad_idle.tick)
        except Exception:
            logger.warning("salad.idle_tick_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    db = SessionLocal()
    try:
        row = get_or_create_panel_settings(db)
        entry = row.entry_path
    finally:
        db.close()
    logger.info(
        "api.startup",
        host=settings.api_host,
        port=settings.api_port,
        auth_required=auth_is_required(),
        panel_entry_path=entry,
    )
    _maybe_start_ollama()
    _maybe_start_worker()
    idle_task = asyncio.create_task(_salad_idle_loop())
    try:
        yield
    finally:
        idle_task.cancel()
        with suppress(asyncio.CancelledError):
            await idle_task
        logger.info("api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Reels Publisher Admin API",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    origins = settings.cors_allowed_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(panel.router)
    app.include_router(auth.router)
    app.include_router(settings_routes.router)
    app.include_router(operators.router)
    app.include_router(dashboard.router)
    app.include_router(accounts.router)
    app.include_router(browser.router)
    app.include_router(proxies.router)
    app.include_router(videos.router)
    app.include_router(jobs.router)
    app.include_router(diagnostics.router)
    app.include_router(publications.router)
    app.include_router(events.router)
    app.include_router(factory.router)
    app.include_router(gpu.router)
    app.include_router(admin_notes.router)
    app.include_router(worker.router)
    app.include_router(assistant.router)
    app.include_router(screenshots.router)
    app.include_router(maintenance.router)

    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi_json(_principal: AuthPrincipal = DocsOwnerDep):
        return app.openapi()

    novnc_dir = Path("/usr/share/novnc")
    if novnc_dir.is_dir():
        app.mount("/novnc", StaticFiles(directory=str(novnc_dir)), name="novnc")

    return app


app = create_app()
