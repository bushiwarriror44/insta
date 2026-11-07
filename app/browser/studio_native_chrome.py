"""Launch Google Chrome for Studio VNC without Playwright / CDP (interactive Google login)."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.accounts.studio_desktop_profile import (
    ensure_studio_desktop_profile,
    studio_playwright_context_kwargs,
)
from app.behavior.playwright_channel import chromium_launch_channel_kwargs, normalize_playwright_channel
from app.behavior.playwright_surface import studio_vnc_launch_args
from app.behavior.warmup_playwright import _parse_proxy
from app.config import settings
from app.geo.timezone_normalize import normalize_playwright_timezone
from app.logging_setup import get_logger

logger = get_logger(__name__)

_CHROME_BIN_CANDIDATES = ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium")

_FORBIDDEN_CHROME_FLAGS = frozenset(
    {
        "--enable-automation",
        "--remote-debugging-pipe",
        "--remote-debugging-port=0",
    }
)


def native_chrome_profile_dir(username: str, platform: str) -> Path:
    path = settings.playwright_dir / platform / username / "chrome_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_google_chrome_binary() -> Path | None:
    for name in _CHROME_BIN_CANDIDATES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def chrome_proxy_server_flag(proxy_url: str) -> str | None:
    url = (proxy_url or "").strip()
    if not url:
        return None
    return f"--proxy-server={url}"


def build_native_chrome_argv(
    *,
    user_data_dir: Path,
    proxy_url: str,
    initial_url: str,
    desktop_geometry: tuple[int, int] | None,
) -> list[str]:
    binary = resolve_google_chrome_binary()
    if binary is None:
        raise RuntimeError("google-chrome-stable не найден")

    argv: list[str] = [str(binary)]
    argv.extend(studio_vnc_launch_args(desktop_geometry))
    for arg in argv[1:]:
        if arg.startswith("--remote-debugging"):
            raise RuntimeError(f"unexpected debug flag in studio args: {arg}")

    argv.append(f"--user-data-dir={user_data_dir}")
    proxy_flag = chrome_proxy_server_flag(proxy_url)
    if proxy_flag:
        argv.append(proxy_flag)

    argv = [
        a
        for a in argv
        if a not in _FORBIDDEN_CHROME_FLAGS and not str(a).startswith("--remote-debugging")
    ]
    argv.append(initial_url)
    return argv


def launch_native_chrome(
    *,
    user_data_dir: Path,
    proxy_url: str,
    display: str,
    initial_url: str,
    desktop_geometry: tuple[int, int] | None,
) -> subprocess.Popen[Any]:
    argv = build_native_chrome_argv(
        user_data_dir=user_data_dir,
        proxy_url=proxy_url,
        initial_url=initial_url,
        desktop_geometry=desktop_geometry,
    )
    env = os.environ.copy()
    env["DISPLAY"] = display
    env.pop("CHROME_DESKTOP", None)
    proc = subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    logger.info(
        "studio_native_chrome.started",
        pid=proc.pid,
        user_data_dir=str(user_data_dir),
        display=display,
        url=initial_url,
    )
    return proc


def native_chrome_running(proc: subprocess.Popen[Any] | None) -> bool:
    return proc is not None and proc.poll() is None


async def stop_native_chrome(
    proc: subprocess.Popen[Any] | None,
    *,
    term_timeout_sec: float = 12.0,
) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    if sys.platform != "win32":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, OSError, AttributeError):
            try:
                proc.terminate()
            except OSError:
                return
    else:
        try:
            proc.terminate()
        except OSError:
            return
    deadline = time.monotonic() + term_timeout_sec
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            logger.info("studio_native_chrome.stopped", pid=proc.pid, graceful=True)
            return
        await asyncio.sleep(0.25)
    if sys.platform != "win32":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError, AttributeError):
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            proc.kill()
        except OSError:
            pass
    logger.warning("studio_native_chrome.killed", pid=proc.pid)


async def export_storage_state_from_native_profile(
    *,
    username: str,
    platform: str,
    proxy_url: str,
    proxy_country: str | None,
    proxy_timezone: str | None,
    state_out: Path,
) -> None:
    """Open the on-disk Chrome profile headlessly via Playwright only to dump storage_state."""
    from playwright.async_api import async_playwright

    profile_dir = native_chrome_profile_dir(username, platform)
    proxy_arg = _parse_proxy(proxy_url)
    if not proxy_arg:
        raise RuntimeError("нужен прокси для экспорта cookies")

    studio_profile = ensure_studio_desktop_profile(username, platform, proxy_country=proxy_country)
    tz_id = normalize_playwright_timezone(proxy_timezone, country=proxy_country)
    channel = normalize_playwright_channel(settings.browser_vnc_channel)
    channel_kwargs = chromium_launch_channel_kwargs(channel)

    state_out.parent.mkdir(parents=True, exist_ok=True)
    ctx_kwargs = studio_playwright_context_kwargs(studio_profile, timezone_id=tz_id)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=True,
            proxy=proxy_arg,
            ignore_default_args=["--enable-automation"],
            args=studio_vnc_launch_args(
                (settings.browser_studio_vnc_width, settings.browser_studio_vnc_height)
            ),
            locale=ctx_kwargs["locale"],
            timezone_id=ctx_kwargs["timezone_id"],
            user_agent=ctx_kwargs["user_agent"],
            viewport=ctx_kwargs["viewport"],
            device_scale_factor=ctx_kwargs["device_scale_factor"],
            has_touch=ctx_kwargs["has_touch"],
            is_mobile=ctx_kwargs["is_mobile"],
            color_scheme=ctx_kwargs["color_scheme"],
            extra_http_headers=ctx_kwargs["extra_http_headers"],
            **channel_kwargs,
        )
        try:
            await context.storage_state(path=str(state_out))
        finally:
            await context.close()
