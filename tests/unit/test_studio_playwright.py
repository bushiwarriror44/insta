"""Tests for headless Studio login."""
from __future__ import annotations


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


