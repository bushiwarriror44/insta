"""Full account connection diagnostics: proxy health + session probe."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.accounts.device_factory import device_path
from app.accounts.session_export import export_sessionid
from app.accounts.session_manager import (
    ensure_fingerprint_and_proxy,
    probe_session_auth,
    session_path,
)
from app.api.schemas import (
    AccountConnectionTestOut,
    InstagramAuthStepOut,
    ProxyHealthStepOut,
    SessionStorageStepOut,
)
from app.db import Account, Proxy
from app.proxies.pool import ProxyError, health_check_record


def _session_source(
    username: str,
    db_session_id: str | None,
) -> Literal["database", "session_file", "none"]:
    exported = export_sessionid(username, db_session_id=db_session_id)
    if exported is None:
        return "none"
    return exported.source


def _session_file_updated_at(username: str) -> datetime | None:
    path = session_path(username)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def run_account_connection_test(account: Account, db: Session) -> AccountConnectionTestOut:
    """Run proxy + Instagram session diagnostics for a single account."""
    now = datetime.now(timezone.utc)
    username = account.username
    file_exists = session_path(username).exists()
    source = _session_source(username, account.session_id)

    session_storage = SessionStorageStepOut(
        has_session_id=bool(account.session_id),
        session_file_exists=file_exists,
        device_file_exists=device_path(username).exists(),
        session_source=source,
    )

    proxy_assigned = account.proxy_id is not None
    proxy_label: str | None = None
    proxy_health = ProxyHealthStepOut(ok=False, error="No proxy assigned")
    instagram_auth = InstagramAuthStepOut(
        ok=False,
        method="none",
        error="Skipped — fix proxy first",
    )

    if not proxy_assigned:
        return AccountConnectionTestOut(
            username=username,
            proxy_assigned=False,
            proxy_label=None,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=InstagramAuthStepOut(
                ok=False,
                method="none",
                error="No proxy assigned — cannot reach Instagram",
            ),
            overall_ok=False,
            checked_at=now,
        )

    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        proxy_health = ProxyHealthStepOut(ok=False, error="Proxy record missing")
        return AccountConnectionTestOut(
            username=username,
            proxy_assigned=True,
            proxy_label=None,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=InstagramAuthStepOut(
                ok=False,
                method="none",
                error="Proxy record missing",
            ),
            overall_ok=False,
            checked_at=now,
        )

    proxy_label = proxy.label
    is_healthy, snapshot = health_check_record(db, proxy)
    db.refresh(proxy)

    if not is_healthy or snapshot is None:
        proxy_health = ProxyHealthStepOut(
            ok=False,
            error="Proxy health check failed",
        )
        return AccountConnectionTestOut(
            username=username,
            proxy_assigned=True,
            proxy_label=proxy_label,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=InstagramAuthStepOut(
                ok=False,
                method="none",
                error="Proxy unhealthy — session check skipped",
            ),
            overall_ok=False,
            checked_at=now,
        )

    geo_mismatch = bool(
        proxy.country
        and snapshot.country
        and proxy.country.upper() != snapshot.country.upper()
    )
    proxy_health = ProxyHealthStepOut(
        ok=True,
        ip=snapshot.ip,
        geo_country=snapshot.country,
        instagram_reachable=snapshot.instagram_reachable,
        geo_mismatch=geo_mismatch,
    )

    if not snapshot.instagram_reachable:
        return AccountConnectionTestOut(
            username=username,
            proxy_assigned=True,
            proxy_label=proxy_label,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=InstagramAuthStepOut(
                ok=False,
                method="none",
                error="Instagram unreachable through proxy",
            ),
            overall_ok=False,
            checked_at=now,
        )

    fingerprint = ensure_fingerprint_and_proxy(
        username,
        country=proxy.country or "US",
    )
    try:
        probe = probe_session_auth(
            username=username,
            fingerprint=fingerprint,
            proxy_url=proxy.url,
            session_id=account.session_id,
        )
    except ProxyError as exc:
        instagram_auth = InstagramAuthStepOut(
            ok=False,
            method="none",
            error=str(exc),
        )
        overall_ok = False
    else:
        instagram_auth = InstagramAuthStepOut(
            ok=probe.ok,
            method=probe.method,
            ig_username=probe.ig_username,
            error=probe.error,
            challenge=probe.challenge,
        )
        overall_ok = proxy_health.ok and proxy_health.instagram_reachable and probe.ok

    return AccountConnectionTestOut(
        username=username,
        proxy_assigned=True,
        proxy_label=proxy_label,
        proxy_health=proxy_health,
        session_storage=session_storage,
        instagram_auth=instagram_auth,
        overall_ok=overall_ok,
        checked_at=now,
    )
