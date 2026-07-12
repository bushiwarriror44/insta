"""FastAPI entrypoint for the admin web UI."""
from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import accounts, browser, dashboard, diagnostics, events, health, jobs, proxies, publications, videos
from app.config import settings
from app.db import init_db
from app.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    logger.info(
        "api.startup",
        host=settings.api_host,
        port=settings.api_port,
        auth_required=bool(settings.admin_token),
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
