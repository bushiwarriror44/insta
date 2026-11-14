"""Save a live-browser or error-card screenshot for an agent report."""
from __future__ import annotations

import asyncio
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.services.panel_browser import signed_url

logger = get_logger(__name__)

_SUCCESS_SHOTS = frozenset(
    {
        "start_browser",
        "login_account",
        "login_instagram",
        "first_login",
        "ensure_account_session",
        "mint_mobile_session",
    }
)
_BROWSER_NAMES = frozenset(
    {
        "start_browser",
        "browser_status",
        "browser_observe",
        "save_browser_session",
        "submit_browser_code",
        "submit_login_code",
        "wait_plan",
        "capture_browser_shot",
        "login_account",
        "login_instagram",
        "first_login",
        "ensure_account_session",
        "mint_mobile_session",
    }
)


def filename_of(url: str) -> str | None:
    name = (url or "").split("?", 1)[0].rstrip("/").split("/")[-1]
    if name.lower().endswith(".png"):
        return name
    return None


def _save_png(raw: bytes, settings: Settings) -> tuple[str, str]:
    settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    (settings.screenshots_dir / filename).write_bytes(raw)
    return filename, signed_url(filename, settings)


def _font(size: int):
    from PIL import ImageFont

    for path in (
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def write_error_card(message: str, settings: Settings | None = None) -> str | None:
    """PNG that states the failure when the live browser has no page."""
    settings = settings or get_settings()
    text = (message or "Не удалось выполнить задачу").strip()[:900]
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("browser_shots.pil_missing")
        return None
    image = Image.new("RGB", (1100, 640), (15, 23, 42))
    draw = ImageDraw.Draw(image)
    font = _font(22)
    draw.text((32, 28), "Ошибка агента", fill=(248, 113, 113), font=font)
    y = 72
    for line in _wrap(text, 90):
        draw.text((32, y), line, fill=(226, 232, 240), font=font)
        y += 30
        if y > 600:
            break
    out = BytesIO()
    image.save(out, format="PNG")
    _filename, url = _save_png(out.getvalue(), settings)
    return url


def _wrap(text: str, width: int) -> list[str]:
    words = text.replace("\n", " ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        piece = word if not current else f"{current} {word}"
        if len(piece) > width:
            if current:
                lines.append(current)
            current = word
        else:
            current = piece
    if current:
        lines.append(current)
    return lines or [""]


def _live_png(username: str | None) -> bytes | None:
    from app.behavior.browser_vision import capture_viewport_png
    from app.browser.session_manager import browser_session_manager

    session = None
    if username:
        session = browser_session_manager._sessions.get(username)
    if session is None or getattr(session, "page", None) is None:
        open_pages = [
            item
            for item in browser_session_manager._sessions.values()
            if getattr(item, "page", None) is not None
        ]
        session = open_pages[-1] if len(open_pages) == 1 else session
    page = getattr(session, "page", None) if session is not None else None
    loop = getattr(session, "loop", None) if session is not None else None
    if page is None or loop is None:
        return None

    async def _grab() -> bytes:
        return await capture_viewport_png(page)

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if running is loop:
            return None
        future = asyncio.run_coroutine_threadsafe(_grab(), loop)
        data = future.result(timeout=25)
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_shots.live_failed", error=str(exc))
        return None
    return data if isinstance(data, (bytes, bytearray)) and data else None


def _panel_png(
    settings: Settings,
    *,
    db: Session | None,
    token: str | None,
    error: str,
) -> bytes | None:
    from app.services import panel_browser

    try:
        filename = panel_browser.capture("/browser", settings=settings, db=db, token=token)
    except Exception as exc:  # noqa: BLE001
        logger.info("browser_shots.panel_skipped", error=str(exc))
        return None
    path = settings.screenshots_dir / filename
    if not path.is_file():
        return None
    raw = path.read_bytes()
    path.unlink(missing_ok=True)
    return _stamp(raw, error)


def _stamp(raw: bytes, error: str) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return raw
    image = Image.open(BytesIO(raw)).convert("RGB")
    draw = ImageDraw.Draw(image)
    banner = (error or "Ошибка").strip().replace("\n", " ")[:180]
    draw.rectangle((0, 0, image.width, 36), fill=(127, 29, 29))
    draw.text((12, 8), banner, fill=(255, 255, 255), font=_font(16))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def evidence_url(
    db: Session | None,
    *,
    username: str | None = None,
    error: str | None = None,
    settings: Settings | None = None,
    token: str | None = None,
    allow_panel: bool = True,
) -> str | None:
    settings = settings or get_settings()
    live = _live_png(username)
    if live:
        raw = _stamp(live, error) if error else live
        _filename, url = _save_png(raw, settings)
        return url
    if error and allow_panel:
        panel = _panel_png(settings, db=db, token=token, error=error)
        if panel:
            _filename, url = _save_png(panel, settings)
            return url
        return write_error_card(error, settings)
    if error:
        return write_error_card(error, settings)
    return None


def shot_for_tool(
    db: Session,
    name: str,
    args: dict[str, Any],
    result: Any,
    *,
    settings: Settings | None = None,
    token: str | None = None,
) -> str | None:
    """Screenshot after a browser start/login, or after any browser-tool error."""
    if name == "capture_browser_shot" or name not in _BROWSER_NAMES:
        return None
    failed = isinstance(result, dict) and bool(result.get("ошибка"))
    if not failed and name not in _SUCCESS_SHOTS:
        return None
    username = str((args or {}).get("username") or "").strip() or None
    if username is None and isinstance(result, dict):
        found = str(result.get("username") or "").strip()
        username = found or None
    error = str(result.get("ошибка")) if failed and isinstance(result, dict) else None
    try:
        return evidence_url(
            db,
            username=username,
            error=error,
            settings=settings,
            token=token,
            allow_panel=failed,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_shots.attach_failed", error=str(exc))
        return None
