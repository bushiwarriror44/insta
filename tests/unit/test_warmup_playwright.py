"""Tests for app.behavior.warmup_playwright with a fake async_playwright."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path


from app.behavior import warmup_playwright as wp


def test_parse_proxy_full():
    out = wp._parse_proxy("http://user:pwd@host:8000")
    assert out == {"server": "http://host:8000", "username": "user", "password": "pwd"}


def test_parse_proxy_without_credentials():
    out = wp._parse_proxy("http://host:8000")
    assert out == {"server": "http://host:8000"}


def test_parse_proxy_username_only():
    out = wp._parse_proxy("http://user@host:8000")
    assert out == {"server": "http://host:8000", "username": "user"}


def test_parse_proxy_no_scheme():
    out = wp._parse_proxy("host:8000")
    assert out == {"server": "host:8000"}


def test_ua_for_device_uses_fingerprint_android_release():
    """The browser UA is built from the persistent fingerprint's
    android_release + model so all surfaces (API + browser) advertise the
    same hardware."""
    fp_settings = {
        "android_release": "13",
        "manufacturer": "samsung",
        "model": "SM-S908B",
    }
    ua = wp._ua_for_device(fp_settings, fallback_ua=None)
    assert "Android 13" in ua
    assert "SM-S908B" in ua
    assert "Mobile Safari" in ua


def test_ua_for_device_falls_back_when_no_fingerprint():
    ua = wp._ua_for_device(None, fallback_ua="custom-ua")
    assert ua == "custom-ua"


def test_viewport_from_resolution_scales_down():
    vp = wp._viewport_from_resolution("1080x2400")
    assert vp["width"] < 500
    assert vp["height"] < 1000


def test_viewport_from_resolution_falls_back():
    assert wp._viewport_from_resolution(None) == {"width": 412, "height": 915}
    assert wp._viewport_from_resolution("garbage") == {"width": 412, "height": 915}


# --- Fake Playwright machinery ----------------------------------------------


class _AsyncCtx:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_a):
        return False


class FakePage:
    def __init__(self, *, has_login_form: bool = True, has_challenge: bool = False, already_logged_in: bool = False):
        self._has_login_form = has_login_form
        self._has_challenge = has_challenge
        self._already_logged_in = already_logged_in
        self.events: list[tuple[str, tuple, dict]] = []
        self.mouse = self
        self.locator_calls: list[str] = []

    async def goto(self, *args, **kwargs):
        self.events.append(("goto", args, kwargs))

    def locator(self, selector: str):
        self.locator_calls.append(selector)
        page = self

        class _L:
            @property
            def first(self_inner):
                return self_inner

            async def count(self_inner):
                if selector == 'a[href="/explore/"]':
                    return 1 if page._already_logged_in else 0
                if page._has_challenge and "Suspicious" in selector:
                    return 1
                if page._has_challenge and "security_code" in selector:
                    return 1
                return 0

            async def wait_for(self_inner, *_a, **_kw):
                return None

            async def bounding_box(self_inner):
                return {"x": 100.0, "y": 100.0, "width": 200.0, "height": 50.0}

            async def click(self_inner, *args, **kwargs):
                page.events.append(("locator_click", (selector,), kwargs))

            async def type(self_inner, text, *, delay=0):
                page.events.append(("type", (selector, text), {"delay": delay}))

        return _L()

    async def fill(self, *args, **kwargs):
        self.events.append(("fill", args, kwargs))

    async def click(self, *args, **kwargs):
        self.events.append(("click", args, kwargs))

    async def wheel(self, *args, **kwargs):
        self.events.append(("wheel", args, kwargs))

    async def move(self, *args, **kwargs):
        self.events.append(("mouse_move", args, kwargs))

    async def down(self, *args, **kwargs):
        self.events.append(("mouse_down", args, kwargs))

    async def up(self, *args, **kwargs):
        self.events.append(("mouse_up", args, kwargs))


class FakeContext:
    def __init__(self, page: FakePage):
        self.page = page
        self.storage_state_path: str | None = None

    async def new_page(self):
        return self.page

    async def storage_state(self, path: str):
        self.storage_state_path = path
        Path(path).write_text(json.dumps({"saved": True}), encoding="utf-8")

    async def close(self):
        pass


class FakeBrowser:
    def __init__(self, context: FakeContext):
        self._context = context
        self.launch_kwargs: dict = {}

    async def new_context(self, **kwargs):
        self._context.last_kwargs = kwargs
        return self._context

    async def close(self):
        pass


class FakeChromium:
    def __init__(self, browser: FakeBrowser):
        self._browser = browser
        self.launched = False

    async def launch(self, **kwargs):
        self.launched = True
        self._browser.launch_kwargs = kwargs
        return self._browser


class FakePW:
    def __init__(self, page: FakePage):
        self.context = FakeContext(page)
        self.browser = FakeBrowser(self.context)
        self.chromium = FakeChromium(self.browser)


def _patch_async_playwright(monkeypatch, page: FakePage) -> FakePW:
    pw = FakePW(page)

    fake_module = types.ModuleType("playwright.async_api")

    def async_playwright():
        return _AsyncCtx(pw)

    fake_module.async_playwright = async_playwright

    parent = types.ModuleType("playwright")
    parent.async_api = fake_module
    monkeypatch.setitem(sys.modules, "playwright", parent)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_module)
    return pw


def test_first_login_happy_path(monkeypatch, app_env):
    page = FakePage(has_login_form=True, already_logged_in=False)
    _patch_async_playwright(monkeypatch, page)

    monkeypatch.setattr(wp, "asyncio", _SyncAsyncio())

    ok = wp.first_login(
        username="alice",
        password="pwd",
        proxy_url="http://u:p@host:1",
        locale="en_US",
        timezone_id="UTC",
        headless=True,
    )
    assert ok.ok is True
    storage = app_env.tmp_path / "playwright" / "alice" / "state.json"
    assert storage.exists()
    type_calls = [e for e in page.events if e[0] == "type"]
    # Username + password fields both typed.
    typed_text = [e[1][1] for e in type_calls]
    assert "alice" in typed_text
    assert "pwd" in typed_text


def test_first_login_skips_form_when_already_logged_in(monkeypatch, app_env):
    page = FakePage(has_login_form=False, already_logged_in=True)
    _patch_async_playwright(monkeypatch, page)
    monkeypatch.setattr(wp, "asyncio", _SyncAsyncio())

    ok = wp.first_login(
        username="bob",
        password="pwd",
        proxy_url="http://u:p@host:1",
        locale="en_US",
        timezone_id="UTC",
        headless=True,
    )
    assert ok.ok is True
    type_calls = [e for e in page.events if e[0] == "type"]
    assert type_calls == []


def test_first_login_detects_challenge(monkeypatch, app_env):
    page = FakePage(has_login_form=True, has_challenge=True, already_logged_in=False)
    _patch_async_playwright(monkeypatch, page)
    monkeypatch.setattr(wp, "asyncio", _SyncAsyncio())

    ok = wp.first_login(
        username="carol",
        password="pwd",
        proxy_url="http://u:p@host:1",
        locale="en_US",
        timezone_id="UTC",
        headless=True,
    )
    assert ok.ok is False
    assert ok.challenge is True


def test_first_login_requires_proxy_before_browser(monkeypatch, app_env):
    page = FakePage(has_login_form=False, already_logged_in=True)
    pw = _patch_async_playwright(monkeypatch, page)
    monkeypatch.setattr(wp, "asyncio", _SyncAsyncio())

    ok = wp.first_login(
        username="no-proxy",
        password="pwd",
        proxy_url=None,
        locale="en_US",
        timezone_id="UTC",
        headless=True,
    )
    assert ok.ok is False
    assert pw.chromium.launched is False


# --- helpers ----------------------------------------------------------------


class _SyncAsyncio:
    """Minimal asyncio replacement used by warmup_playwright.first_login.

    The real ``warmup_playwright`` calls ``asyncio.run`` and ``asyncio.sleep``.
    We need ``asyncio.run`` to actually drive the coroutine. Easiest path:
    delegate to the real ``asyncio.run`` but neutralize ``sleep``.
    """

    def __init__(self):
        import asyncio as real_asyncio

        self._real = real_asyncio

    def run(self, coro):
        return self._real.run(coro)

    def sleep(self, *_a, **_kw):
        async def _noop():
            return None

        return _noop()
