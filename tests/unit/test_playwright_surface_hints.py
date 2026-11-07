from app.accounts.playwright_surface_hints import login_surface_profile_warnings


def test_warn_when_mobile_but_desktop_profile_exists(app_env):
    from app.accounts.studio_desktop_profile import ensure_desktop_playwright_profile

    ensure_desktop_playwright_profile("hint_user", "instagram", proxy_country="US")
    warnings = login_surface_profile_warnings(
        "hint_user",
        resolved_surface="mobile",
        account_login_surface="mobile",
    )
    assert any("web_desktop_profile" in w for w in warnings)


def test_warn_login_surface_mismatch():
    warnings = login_surface_profile_warnings(
        "u",
        resolved_surface="desktop",
        account_login_surface="mobile",
    )
    assert any("login_surface" in w or "карточке" in w for w in warnings)
