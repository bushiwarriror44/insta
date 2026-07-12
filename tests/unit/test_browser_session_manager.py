"""Browser session manager unit tests (mocked Playwright/VNC)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser.session_manager import BrowserSessionManager, BrowserSessionStatus


@pytest.mark.asyncio
async def test_status_dict_stopped_by_default():
    mgr = BrowserSessionManager()
    data = mgr.status_dict("alice")
    assert data["status"] == BrowserSessionStatus.stopped.value
    assert data["awaiting_code"] is False


@pytest.mark.asyncio
async def test_start_session_disabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "browser_vnc_enabled", False)
    mgr = BrowserSessionManager()
    account = MagicMock(username="alice")
    proxy = MagicMock(url="http://u:p@1.2.3.4:8080", timezone="UTC", country="US")

    with pytest.raises(RuntimeError, match="disabled"):
        await mgr.start_session(account, proxy)


@pytest.mark.asyncio
async def test_submit_code_requires_active_session():
    mgr = BrowserSessionManager()
    account = MagicMock(username="alice")
    db = MagicMock()

    with pytest.raises(RuntimeError, match="No active browser"):
        await mgr.submit_code(db, account, "123456")


@pytest.mark.asyncio
async def test_stop_session_idempotent():
    mgr = BrowserSessionManager()
    await mgr.stop_session("missing-user")
    assert mgr.status_dict("missing-user")["status"] == "stopped"


@pytest.mark.asyncio
async def test_refresh_code_state_sets_awaiting(monkeypatch):
    from app.browser.session_manager import BrowserSessionManager, BrowserSessionState, BrowserSessionStatus
    import app.browser.session_manager as sm

    mgr = BrowserSessionManager()
    page = AsyncMock()
    page.url = "https://www.instagram.com/challenge/"
    session = BrowserSessionState(username="bob", page=page, status=BrowserSessionStatus.running)
    mgr._sessions["bob"] = session

    async def fake_detect(*_a, **_k):
        return True

    monkeypatch.setattr(sm, "_detect_2fa_required", fake_detect)
    monkeypatch.setattr(sm, "_detect_challenge", AsyncMock(return_value=False))

    await mgr._refresh_code_state(session)
    assert session.awaiting_code is True
    assert session.status == BrowserSessionStatus.awaiting_code


@pytest.mark.asyncio
async def test_save_session_rejects_when_not_logged_in(monkeypatch):
    import app.browser.session_manager as sm
    from app.browser.session_manager import BrowserSessionManager, BrowserSessionState, BrowserSessionStatus

    mgr = BrowserSessionManager()
    session = BrowserSessionState(
        username="alice",
        context=MagicMock(),
        page=MagicMock(),
        status=BrowserSessionStatus.running,
    )
    mgr._sessions["alice"] = session

    async def _not_logged_in(*_a, **_k):
        return False

    monkeypatch.setattr(sm, "_is_logged_in", _not_logged_in)

    with pytest.raises(RuntimeError, match="войдите"):
        await mgr.save_session(MagicMock(), MagicMock(username="alice"))


@pytest.mark.asyncio
async def test_start_session_uses_mobile_surface(monkeypatch):
    from app.config import settings
    import app.browser.session_manager as sm

    monkeypatch.setattr(settings, "browser_vnc_enabled", True)
    monkeypatch.setattr(sm, "vnc_stack_available", lambda: True)
    monkeypatch.setattr(sm, "playwright_browsers_available", lambda: True)

    captured: dict = {}

    class FakeVnc:
        def __init__(self, **kwargs):
            captured["vnc_screen"] = kwargs.get("screen")

        async def start(self):
            return None

    monkeypatch.setattr(sm, "VncStack", FakeVnc)

    async def fake_launch(session, account, proxy, *, autofill_login, surface):
        captured["surface"] = surface

    mgr = BrowserSessionManager()
    account = MagicMock(username="alice")
    proxy = MagicMock(url="http://u:p@1.2.3.4:8080", timezone="UTC", country="US")

    monkeypatch.setattr(mgr, "_launch_browser", fake_launch)
    monkeypatch.setattr(mgr, "_poll_session", AsyncMock())
    monkeypatch.setattr(mgr, "_auto_stop", AsyncMock())

    await mgr.start_session(account, proxy, surface="mobile")
    assert captured["surface"] == "mobile"
    assert captured["vnc_screen"] == "430x932x24"
