"""Tests for headless Studio login."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.behavior import studio_playwright as sp


def test_studio_login_skips_when_session_ready(monkeypatch):
    monkeypatch.setattr(sp, "studio_session_ready", lambda u, p: True)
    monkeypatch.setattr(sp, "playwright_browsers_available", lambda: True)

    out = sp.studio_login(
        username="ytuser",
        password="secret",
        proxy_url="http://u:p@host:1",
        platform="youtube",
    )
    assert out.ok is True


def test_try_resolve_challenge_detects_google_url():
    assert sp._google_challenge_url("https://accounts.google.com/v3/signin/challenge/totp") is True


def test_evaluate_studio_liveness_ok_on_studio_url():
    out = sp.evaluate_studio_liveness(
        page_url="https://studio.youtube.com/channel/abc",
        platform="youtube",
        needs_login=False,
        challenge=False,
    )
    assert out.ok is True


def test_evaluate_studio_liveness_stale_when_google_login():
    out = sp.evaluate_studio_liveness(
        page_url="https://accounts.google.com/signin",
        platform="youtube",
        needs_login=True,
        challenge=False,
    )
    assert out.ok is False
    assert out.challenge is False


def test_evaluate_studio_liveness_challenge():
    out = sp.evaluate_studio_liveness(
        page_url="https://studio.youtube.com/",
        platform="youtube",
        needs_login=False,
        challenge=True,
    )
    assert out.ok is False
    assert out.challenge is True


def test_probe_liveness_skips_without_cookies(monkeypatch):
    monkeypatch.setattr(sp, "studio_session_ready", lambda u, p: False)
    out = sp.probe_studio_session_liveness(
        username="u",
        proxy_url="http://x:1",
        platform="youtube",
    )
    assert out.ok is False
    assert "диске" in (out.error or "").lower()


@pytest.mark.asyncio
async def test_try_google_identifier_uses_human_type_not_fill(monkeypatch):
    human = AsyncMock()
    monkeypatch.setattr("app.behavior.warmup_playwright._human_type_locator", human)
    monkeypatch.setattr(sp.asyncio, "sleep", AsyncMock())

    loc = MagicMock()
    loc.count = AsyncMock(return_value=1)
    loc.wait_for = AsyncMock()
    loc.fill = AsyncMock()

    chain = MagicMock()
    chain.first = loc
    page = MagicMock()
    page.locator = MagicMock(return_value=chain)

    next_btn = MagicMock()
    next_btn.count = AsyncMock(return_value=0)
    page.get_by_role = MagicMock(return_value=next_btn)
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()

    ok = await sp._try_google_identifier(page, "user@example.com")
    assert ok is True
    human.assert_awaited_once()
    loc.fill.assert_not_awaited()


