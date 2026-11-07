from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.browser import studio_native_chrome as snc


def test_build_native_chrome_argv_user_data_proxy_no_debug(monkeypatch):
    monkeypatch.setattr(snc, "resolve_google_chrome_binary", lambda: Path("/usr/bin/google-chrome-stable"))

    argv = snc.build_native_chrome_argv(
        user_data_dir=Path("/data/playwright/youtube/alice/chrome_profile"),
        proxy_server_value="http://127.0.0.1:18080",
        initial_url="https://studio.youtube.com",
        desktop_geometry=(1024, 640),
    )
    assert Path(argv[0]) == Path("/usr/bin/google-chrome-stable")
    user_data_flags = [a for a in argv if a.startswith("--user-data-dir=")]
    assert len(user_data_flags) == 1
    assert user_data_flags[0].endswith("alice\\chrome_profile") or user_data_flags[0].endswith(
        "alice/chrome_profile"
    )
    proxy_flags = [a for a in argv if a.startswith("--proxy-server=")]
    assert len(proxy_flags) == 1
    assert "@" not in proxy_flags[0]
    assert "127.0.0.1:18080" in proxy_flags[0]
    assert argv[-1] == "https://studio.youtube.com"
    assert not any(str(a).startswith("--remote-debugging") for a in argv)
    assert "--enable-automation" not in argv
    assert "--disable-quic" in argv


def test_native_chrome_profile_dir_layout(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "playwright_dir", tmp_path / "pw")
    path = snc.native_chrome_profile_dir("bob", "youtube")
    assert path == tmp_path / "pw" / "youtube" / "bob" / "chrome_profile"
    assert path.is_dir()


@pytest.mark.asyncio
async def test_save_native_studio_exports_state(monkeypatch, tmp_path):
    import app.browser.session_manager as sm

    mgr = sm.BrowserSessionManager()
    session = sm.BrowserSessionState(
        username="yt",
        status=sm.BrowserSessionStatus.running,
        native_chrome_mode=True,
        native_chrome_proc=MagicMock(poll=lambda: None),
        proxy_url="http://u:p@1.2.3.4:8080",
        proxy_country="AM",
        proxy_timezone="Asia/Yerevan",
    )
    mgr._sessions["yt"] = session

    state_file = tmp_path / "youtube" / "yt" / "state.json"
    state_file.parent.mkdir(parents=True)
    cookies = [{"name": "SID", "value": "x", "domain": ".google.com", "path": "/"}]
    state_file.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")

    export = AsyncMock()

    async def _export(**_kwargs):
        return None

    export.side_effect = _export
    stop = AsyncMock()
    monkeypatch.setattr(sm, "export_storage_state_from_native_profile", export)
    monkeypatch.setattr(sm, "stop_native_chrome", stop)
    monkeypatch.setattr(sm, "playwright_state_write_path", lambda u, p: state_file)

    account = MagicMock()
    account.username = "yt"
    account.platform = MagicMock(value="youtube")

    db = MagicMock()
    result = await mgr.save_session(db, account)
    stop.assert_awaited_once()
    export.assert_awaited_once()
    assert result["playwright_state_saved"] is True
    assert session.status == sm.BrowserSessionStatus.saved
