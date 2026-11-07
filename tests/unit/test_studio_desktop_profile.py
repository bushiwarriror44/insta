from app.accounts.device_factory import primary_locale_for_country
from app.accounts.studio_desktop_profile import (
    desktop_chrome_user_agent,
    desktop_profile_path,
    ensure_desktop_playwright_profile,
    ensure_studio_desktop_profile,
    studio_desktop_profile_path,
)


def test_primary_locale_for_country(app_env):
    assert primary_locale_for_country("DE") == "de-DE"
    assert primary_locale_for_country("US") == "en-US"


def test_ensure_studio_desktop_profile_stable_ua(app_env, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "browser_studio_vnc_width", 1024)
    monkeypatch.setattr(settings, "browser_studio_vnc_height", 640)
    monkeypatch.setattr(
        "app.accounts.studio_desktop_profile._pick_chrome_major",
        lambda: "131",
    )

    p1 = ensure_studio_desktop_profile("u1", "youtube", proxy_country="DE")
    p2 = ensure_studio_desktop_profile("u1", "youtube", proxy_country="DE")
    assert p1.user_agent == p2.user_agent
    assert p1.locale == "de-DE"
    assert p1.viewport_width == 1024
    assert studio_desktop_profile_path("u1", "youtube").exists()


def test_desktop_chrome_user_agent():
    ua = desktop_chrome_user_agent("131")
    assert "Chrome/131.0.0.0" in ua


def test_ensure_instagram_desktop_profile_stable_ua(app_env, monkeypatch):
    monkeypatch.setattr(
        "app.accounts.studio_desktop_profile._pick_chrome_major",
        lambda: "131",
    )
    p1 = ensure_desktop_playwright_profile("ig1", "instagram", proxy_country="US")
    p2 = ensure_desktop_playwright_profile("ig1", "instagram", proxy_country="US")
    assert p1.user_agent == p2.user_agent
    assert p1.viewport_width == 1280
    assert p1.viewport_height == 800
    assert p1.locale == "en-US"
    assert desktop_profile_path("ig1", "instagram").name == "web_desktop_profile.json"


def test_ensure_playwright_chrome_major_persists(app_env, monkeypatch):
    from app.accounts.device_factory import ensure_playwright_chrome_major, load_fingerprint

    monkeypatch.setattr(
        "app.accounts.studio_desktop_profile.pick_playwright_chrome_major",
        lambda: "132",
    )
    m1 = ensure_playwright_chrome_major("ig_major_test")
    m2 = ensure_playwright_chrome_major("ig_major_test")
    assert m1 == m2 == "132"
    fp = load_fingerprint("ig_major_test")
    assert fp is not None
    ds = fp.settings["device_settings"]
    assert ds["playwright_chrome_major"] == "132"
