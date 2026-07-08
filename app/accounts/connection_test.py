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
    DiagnosticLogLineOut,
    InstagramAuthStepOut,
    ProxyHealthStepOut,
    SessionStorageStepOut,
)
from app.db import Account, DiagnosticRunKind, Proxy
from app.diagnostics.collector import DiagnosticCollector
from app.proxies.pool import ProxyError, health_check_record


def _session_source(
    username: str,
    db_session_id: str | None,
) -> Literal["database", "session_file", "none"]:
    exported = export_sessionid(username, db_session_id=db_session_id)
    if exported is None:
        return "none"
    return exported.source


def _finish(
    collector: DiagnosticCollector,
    *,
    overall_ok: bool,
    summary: str,
    username: str,
    proxy_assigned: bool,
    proxy_label: str | None,
    proxy_health: ProxyHealthStepOut,
    session_storage: SessionStorageStepOut,
    instagram_auth: InstagramAuthStepOut,
    now: datetime,
) -> AccountConnectionTestOut:
    status: Literal["ok", "warn", "fail"] = "ok" if overall_ok else "fail"
    if not overall_ok and proxy_health.ok and proxy_health.geo_mismatch:
        status = "warn"
    collector.finish(status, summary)
    return AccountConnectionTestOut(
        username=username,
        proxy_assigned=proxy_assigned,
        proxy_label=proxy_label,
        proxy_health=proxy_health,
        session_storage=session_storage,
        instagram_auth=instagram_auth,
        overall_ok=overall_ok,
        checked_at=now,
        run_id=collector.run_id,
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
    )


def run_account_connection_test(account: Account, db: Session) -> AccountConnectionTestOut:
    """Run proxy + Instagram session diagnostics for a single account."""
    now = datetime.now(timezone.utc)
    username = account.username
    collector = DiagnosticCollector(
        db,
        kind=DiagnosticRunKind.connection_test,
        account_id=account.id,
    )

    file_exists = session_path(username).exists()
    device_exists = device_path(username).exists()
    source = _session_source(username, account.session_id)

    session_storage = SessionStorageStepOut(
        has_session_id=bool(account.session_id),
        session_file_exists=file_exists,
        device_file_exists=device_exists,
        session_source=source,
    )
    collector.info(
        "storage",
        f"session source={source}, db sessionid={'yes' if account.session_id else 'no'}, "
        f"cookies file={'yes' if file_exists else 'no'}, device file={'yes' if device_exists else 'no'}",
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
        collector.error("proxy", "No proxy assigned")
        return _finish(
            collector,
            overall_ok=False,
            summary="No proxy assigned",
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
            now=now,
        )

    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        collector.error("proxy", "Proxy record missing in database")
        proxy_health = ProxyHealthStepOut(ok=False, error="Proxy record missing")
        return _finish(
            collector,
            overall_ok=False,
            summary="Proxy record missing",
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
            now=now,
        )

    proxy_label = proxy.label
    collector.info("proxy", f"Using proxy {proxy_label}")

    is_healthy, snapshot, health_error = health_check_record(db, proxy)
    db.refresh(proxy)

    if not is_healthy or snapshot is None:
        err = health_error or "Proxy health check failed"
        collector.error("proxy_health", err)
        proxy_health = ProxyHealthStepOut(ok=False, error=err)
        return _finish(
            collector,
            overall_ok=False,
            summary=err,
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
            now=now,
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
    collector.info(
        "proxy_health",
        f"IP={snapshot.ip or 'unknown'}, geo={snapshot.country or 'unknown'}, "
        f"instagram_reachable={snapshot.instagram_reachable}",
    )
    if geo_mismatch:
        collector.warn(
            "proxy_health",
            f"Geo mismatch: advertised {proxy.country}, actual {snapshot.country}",
        )

    if health_error or not snapshot.instagram_reachable:
        err = health_error or "Instagram unreachable through proxy"
        collector.error("instagram_reach", err)
        return _finish(
            collector,
            overall_ok=False,
            summary=err,
            username=username,
            proxy_assigned=True,
            proxy_label=proxy_label,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=InstagramAuthStepOut(
                ok=False,
                method="none",
                error=err,
            ),
            now=now,
        )

    collector.info("fingerprint", "Loading device fingerprint")
    fingerprint = ensure_fingerprint_and_proxy(
        username,
        country=proxy.country or "US",
    )
    collector.info("session_probe", "Validating Instagram session")
    try:
        probe = probe_session_auth(
            username=username,
            fingerprint=fingerprint,
            proxy_url=proxy.url,
            session_id=account.session_id,
        )
    except ProxyError as exc:
        collector.error("session_probe", str(exc))
        instagram_auth = InstagramAuthStepOut(
            ok=False,
            method="none",
            error=str(exc),
        )
        return _finish(
            collector,
            overall_ok=False,
            summary=str(exc),
            username=username,
            proxy_assigned=True,
            proxy_label=proxy_label,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=instagram_auth,
            now=now,
        )

    instagram_auth = InstagramAuthStepOut(
        ok=probe.ok,
        method=probe.method,
        ig_username=probe.ig_username,
        error=probe.error,
        challenge=probe.challenge,
    )
    if probe.ok:
        collector.info(
            "session_probe",
            f"Authenticated via {probe.method}"
            + (f" as @{probe.ig_username}" if probe.ig_username else ""),
        )
    elif probe.challenge:
        collector.warn("session_probe", probe.error or "Challenge required")
    else:
        collector.error("session_probe", probe.error or "Session validation failed")

    overall_ok = proxy_health.ok and proxy_health.instagram_reachable and probe.ok
    summary = (
        "Ready for autoposting"
        if overall_ok
        else (probe.error or health_error or "Connection check failed")
    )
    return _finish(
        collector,
        overall_ok=overall_ok,
        summary=summary,
        username=username,
        proxy_assigned=True,
        proxy_label=proxy_label,
        proxy_health=proxy_health,
        session_storage=session_storage,
        instagram_auth=instagram_auth,
        now=now,
    )
