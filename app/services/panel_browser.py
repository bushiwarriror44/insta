"""A headless browser that looks at this panel's own pages."""

from __future__ import annotations

import time
import uuid

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.panel.settings_store import get_or_create_panel_settings
from app.services.media import MediaError, resolve
from app.services.media_links import relative_url

TOKEN_KEY = "reels-admin-token"
SCREENSHOT_TIMEOUT_MS = 15_000
SETTLE_MS = 1_200
VIEWPORT = {"width": 1440, "height": 900}


class BrowserError(RuntimeError):
    pass


def capture(
    path: str,
    *,
    settings: Settings | None = None,
    db: Session | None = None,
    token: str | None = None,
) -> str:
    settings = settings or get_settings()
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserError("браузер для снимков не установлен — playwright install chromium") from exc

    settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    dest = settings.screenshots_dir / filename
    prefix = ""
    if db is not None:
        row = get_or_create_panel_settings(db)
        if row.entry_path and row.entry_path != "/":
            prefix = row.entry_path.rstrip("/")
    url = f"{settings.panel_base_url.rstrip('/')}{prefix}{path}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(viewport=VIEWPORT)
                if token:
                    context.add_init_script(
                        f"window.localStorage.setItem({TOKEN_KEY!r}, {token!r})"
                    )
                page = context.new_page()
                page.goto(url, wait_until="load", timeout=SCREENSHOT_TIMEOUT_MS)
                time.sleep(SETTLE_MS / 1000)
                page.screenshot(path=str(dest), full_page=False)
            finally:
                browser.close()
    except PlaywrightError as exc:
        dest.unlink(missing_ok=True)
        raise BrowserError(f"не удалось открыть панель: {exc}") from exc

    return filename


def signed_url(filename: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    try:
        resolve(settings.screenshots_dir, filename)
    except MediaError as exc:
        raise BrowserError(str(exc)) from exc
    return relative_url(filename, prefix="/api/screenshots", settings=settings)
