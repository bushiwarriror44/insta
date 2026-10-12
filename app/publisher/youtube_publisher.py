"""Unofficial YouTube Shorts upload via Playwright (Studio), not Data API."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.accounts.playwright_session import playwright_state_path
from app.logging_setup import get_logger
from app.publisher.reels_publisher import HardPublishError, PublishResult, TemporaryPublishError

logger = get_logger(__name__)

STUDIO_UPLOAD_URL = "https://studio.youtube.com/channel/upload"
LogFn = Callable[[str, str], None]


def _emit_log(on_log, message: str) -> None:
    if not on_log:
        logger.info("youtube.publish", message=message)
        return
    try:
        on_log("info", "publish", message)
    except TypeError:
        on_log("info", message)


def publish_youtube_short(
    *,
    username: str,
    video_path: Path,
    title: str,
    description: str = "",
    tags: str = "",
    privacy: str = "public",
    proxy_url: str,
    fingerprint: dict[str, Any] | None = None,
    on_log: LogFn | None = None,
    timeout_ms: int = 180_000,
) -> PublishResult:
    """Upload a vertical clip through YouTube Studio with saved cookies.

    Requires a Playwright storage_state (browser login / cookie import) and
    a per-account proxy. Official OAuth is not used.
    """
    from playwright.sync_api import sync_playwright

    if not video_path.exists():
        raise HardPublishError(f"видео отсутствует: {video_path}")
    state = playwright_state_path(username, "youtube")
    if not state.exists():
        raise TemporaryPublishError(
            "нет сессии YouTube — откройте браузер и сохраните cookies"
        )

    title = (title or video_path.stem)[:100]
    desc = description
    if tags and "#shorts" not in (title + desc).lower():
        desc = f"{desc}\n#Shorts".strip() if desc else "#Shorts"

    _emit_log(on_log, f"Загрузка в YouTube Studio: {video_path.name}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
        )
        context = browser.new_context(storage_state=str(state))
        page = context.new_page()
        try:
            page.goto(STUDIO_UPLOAD_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            file_input = page.locator("input[type=file]").first
            file_input.wait_for(state="attached", timeout=timeout_ms)
            file_input.set_input_files(str(video_path))
            title_box = page.locator("#textbox").first
            title_box.wait_for(state="visible", timeout=timeout_ms)
            title_box.fill(title)
            if desc:
                boxes = page.locator("#textbox")
                if boxes.count() > 1:
                    boxes.nth(1).fill(desc)
            next_btn = page.get_by_role("button", name="Next")
            for _ in range(3):
                if next_btn.count():
                    next_btn.click()
                    page.wait_for_timeout(800)
            if privacy == "public":
                vis = page.get_by_role("radio", name="Public")
                if vis.count():
                    vis.first.click()
            done = page.get_by_role("button", name="Publish")
            if not done.count():
                done = page.get_by_role("button", name="Done")
            if done.count():
                done.first.click()
            page.wait_for_timeout(4000)
            url = page.url
        except Exception as exc:
            raise TemporaryPublishError(str(exc)) from exc
        finally:
            context.close()
            browser.close()

    return PublishResult(
        media_id=url or "youtube",
        media_code=None,
        final_video_path=video_path,
        final_caption=title,
    )
