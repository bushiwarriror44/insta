"""Unofficial TikTok upload via Playwright (Creator Studio), not Content Posting API."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.accounts.playwright_session import playwright_state_path
from app.logging_setup import get_logger
from app.publisher.reels_publisher import HardPublishError, PublishResult, TemporaryPublishError

logger = get_logger(__name__)

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
LogFn = Callable[[str, str], None]


def _emit_log(on_log, message: str) -> None:
    if not on_log:
        logger.info("tiktok.publish", message=message)
        return
    try:
        on_log("info", "publish", message)
    except TypeError:
        on_log("info", message)


def _caption(title: str, description: str, tags: str) -> str:
    parts = [title.strip(), description.strip()]
    extra = " ".join(f"#{t.strip().lstrip('#')}" for t in tags.split(",") if t.strip())
    if extra:
        parts.append(extra)
    return "\n".join(p for p in parts if p)[:2200]


def publish_tiktok(
    *,
    username: str,
    video_path: Path,
    title: str,
    description: str = "",
    tags: str = "",
    proxy_url: str,
    fingerprint: dict[str, Any] | None = None,
    on_log: LogFn | None = None,
    timeout_ms: int = 180_000,
) -> PublishResult:
    """Upload a clip through TikTok Studio with saved cookies and proxy."""
    from playwright.sync_api import sync_playwright

    if not video_path.exists():
        raise HardPublishError(f"video missing: {video_path}")
    state = playwright_state_path(username)
    if not state.exists():
        raise TemporaryPublishError("TikTok session missing — open browser and save cookies")

    caption = _caption(title or video_path.stem, description, tags)
    _emit_log(on_log, f"TikTok Studio upload {video_path.name}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
        )
        context = browser.new_context(storage_state=str(state))
        page = context.new_page()
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            file_input = page.locator("input[type=file]").first
            file_input.wait_for(state="attached", timeout=timeout_ms)
            file_input.set_input_files(str(video_path))
            caption_box = page.locator('[contenteditable="true"]').first
            if caption_box.count():
                caption_box.fill(caption)
            post_btn = page.get_by_role("button", name="Post")
            if not post_btn.count():
                post_btn = page.get_by_role("button", name="Publish")
            if post_btn.count():
                post_btn.first.click()
            page.wait_for_timeout(4000)
            url = page.url
        except Exception as exc:
            raise TemporaryPublishError(str(exc)) from exc
        finally:
            context.close()
            browser.close()

    return PublishResult(
        media_id=url or "tiktok",
        media_code=None,
        final_video_path=video_path,
        final_caption=caption,
    )
