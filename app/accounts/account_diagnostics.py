"""Diagnostic log helpers for account credential visibility during debugging."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.accounts.login_identifier import resolve_login_identifier

if TYPE_CHECKING:
    from app.db import Account, Proxy
    from app.diagnostics.collector import DiagnosticCollector


def log_account_credentials(
    collector: DiagnosticCollector,
    account: Account,
    proxy: Proxy | None = None,
) -> None:
    """Write account login fields to the diagnostic log (admin debugging)."""
    login_id = resolve_login_identifier(account)
    collector.info("account", f"Панель: @{account.username}")
    collector.info("account", f"Логин Instagram: {login_id}")
    collector.info("account", f"Пароль: {account.password or '—'}")
    if account.login_identifier:
        collector.info("account", f"login_identifier в БД: {account.login_identifier}")
    if account.email:
        collector.info("account", f"Email: {account.email}")
    collector.info("account", f"TOTP seed: {'задан' if account.totp_seed else 'нет'}")
    if proxy is not None:
        collector.info("account", f"Прокси: {proxy.label} ({proxy.country or '?'})")
