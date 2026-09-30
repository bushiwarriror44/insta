"""Autonomous account login (Instagram + YouTube/TikTok Studio)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from sqlalchemy.orm import Session

from app.accounts.email_handler import imap_configuration_error
from app.api.schemas import FirstLoginOut
from app.db import Account

StatusCallback = Callable[[str, Optional[str]], None]


def _platform_value(account: Account) -> str:
    platform = getattr(account, "platform", None)
    if platform is None:
        return "instagram"
    return getattr(platform, "value", platform) or "instagram"


def run_autonomous_account_login(
    account: Account,
    db: Session,
    *,
    surface: str | None = None,
    on_status: StatusCallback | None = None,
) -> FirstLoginOut:
    plat = _platform_value(account)
    if plat in ("youtube", "tiktok"):
        from app.accounts.studio_login_service import run_studio_login

        return run_studio_login(account, db, on_status=on_status)
    return run_autonomous_instagram_login(account, db, surface=surface, on_status=on_status)


def run_autonomous_instagram_login(
    account: Account,
    db: Session,
    *,
    surface: str | None = None,
    on_status: StatusCallback | None = None,
) -> FirstLoginOut:
    from app.accounts.first_login_service import run_account_first_login

    def ping(title: str, detail: str | None = None) -> None:
        if on_status:
            on_status(title, detail)

    ping("Проверяю данные для входа")
    mail = (account.email or "").strip()
    if mail and (account.email_password or "").strip():
        imap_err = imap_configuration_error(mail, (account.imap_host or "").strip() or None)
        if imap_err:
            ping("Почта", imap_err)
        else:
            ping("Почта", "буду читать код подтверждения через IMAP")
    ping("Запускаю автовход (браузер и API)")
    return run_account_first_login(account, db, surface=surface, on_status=on_status)
