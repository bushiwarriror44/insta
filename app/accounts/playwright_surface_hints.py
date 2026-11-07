"""Warnings when Instagram login_surface disagrees with persisted Playwright profiles."""
from __future__ import annotations

from app.accounts.device_factory import load_fingerprint
from app.accounts.studio_desktop_profile import desktop_profile_path
from app.behavior.playwright_surface import resolve_playwright_surface


def login_surface_profile_warnings(
    username: str,
    *,
    resolved_surface: str,
    account_login_surface: str | None = None,
) -> list[str]:
    """Return human-readable warnings for mismatched mobile/desktop browser identity."""
    surface = resolve_playwright_surface(resolved_surface)
    configured = (
        resolve_playwright_surface(account_login_surface)
        if account_login_surface
        else None
    )
    warnings: list[str] = []

    if configured is not None and configured != surface:
        warnings.append(
            f"Поверхность запуска «{surface}», в карточке указано «{configured}». "
            "Для стабильного отпечатка выровняйте login_surface и повторяйте вход на той же поверхности."
        )

    desktop_path = desktop_profile_path(username, "instagram")
    has_desktop_profile = desktop_path.exists()
    fp = load_fingerprint(username)
    has_mobile_major = False
    if fp is not None:
        ds = fp.settings.get("device_settings")
        if isinstance(ds, dict) and ds.get("playwright_chrome_major"):
            has_mobile_major = True

    if surface == "mobile" and has_desktop_profile:
        warnings.append(
            "На диске есть web_desktop_profile.json, но браузер запущен как mobile — "
            "cookies/UA могут расходиться с прошлым desktop-входом. Лучше desktop или очистите профиль."
        )
    if surface == "desktop" and has_mobile_major and not has_desktop_profile:
        warnings.append(
            "В device задан playwright_chrome_major (mobile), профиль desktop ещё не создан — "
            "первый desktop-запуск создаст отдельный отпечаток."
        )

    return warnings
