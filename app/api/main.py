"""FastAPI entrypoint for the admin web UI."""
from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    accounts,
    auth,
    browser,
    dashboard,
    diagnostics,
    events,
    health,
    jobs,
    operators,
    panel,
    proxies,
    publications,
    settings as settings_routes,
    videos,
)
from app.config import settings
from app.db import SessionLocal, init_db
from app.logging_setup import configure_logging, get_logger
from app.panel.settings_store import auth_is_required, get_or_create_panel_settings

logger = get_logger(__name__)


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
    yield
    logger.info("api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Reels Publisher Admin API",
        version="0.2.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
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

    novnc_dir = Path("/usr/share/novnc")
    if novnc_dir.is_dir():
        app.mount("/novnc", StaticFiles(directory=str(novnc_dir)), name="novnc")

    return app


app = create_app()
