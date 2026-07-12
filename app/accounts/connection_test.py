"""Full account connection diagnostics: proxy health + session probe."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.accounts.account_diagnostics import log_account_credentials
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
from app.geo.country_codes import countries_mismatch, normalize_country_code
from app.proxies.pool import ProxyError, health_check_record

_SESSION_SOURCE_LABEL: dict[str, str] = {
    "database": "БД",
    "session_file": "файл",
    "none": "нет",
}


def _session_source(
    username: str,
    db_session_id: str | None,
) -> Literal["database", "session_file", "none"]:
    exported = export_sessionid(username, db_session_id=db_session_id)
    if exported is None:
        return "none"
    return exported.source


def _yes_no(value: bool) -> str:
    return "да" if value else "нет"


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

    proxy_for_log = db.get(Proxy, account.proxy_id) if account.proxy_id else None
    log_account_credentials(collector, account, proxy_for_log)

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
        f"источник сессии={_SESSION_SOURCE_LABEL.get(source, source)}, "
        f"sessionid в БД={_yes_no(bool(account.session_id))}, "
        f"файл cookies={_yes_no(file_exists)}, "
        f"файл устройства={_yes_no(device_exists)}",
    )

    proxy_assigned = account.proxy_id is not None
    proxy_label: str | None = None
    proxy_health = ProxyHealthStepOut(ok=False, error="Прокси не назначен")
    instagram_auth = InstagramAuthStepOut(
        ok=False,
        method="none",
        error="Пропущено — сначала исправьте прокси",
    )

    if not proxy_assigned:
        collector.error("proxy", "Прокси не назначен")
        return _finish(
            collector,
            overall_ok=False,
            summary="Прокси не назначен",
            username=username,
            proxy_assigned=False,
            proxy_label=None,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=InstagramAuthStepOut(
                ok=False,
                method="none",
                error="Прокси не назначен — Instagram недоступен",
            ),
            now=now,
        )

    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        collector.error("proxy", "Запись прокси отсутствует в БД")
        proxy_health = ProxyHealthStepOut(ok=False, error="Запись прокси отсутствует")
        return _finish(
            collector,
            overall_ok=False,
            summary="Запись прокси отсутствует",
            username=username,
            proxy_assigned=True,
            proxy_label=None,
            proxy_health=proxy_health,
            session_storage=session_storage,
            instagram_auth=InstagramAuthStepOut(
                ok=False,
                method="none",
                error="Запись прокси отсутствует",
            ),
            now=now,
        )

    proxy_label = proxy.label
    collector.info("proxy", f"Используется прокси {proxy_label}")

    is_healthy, snapshot, health_error = health_check_record(db, proxy)
    db.refresh(proxy)

    if not is_healthy or snapshot is None:
        err = health_error or "Проверка прокси не пройдена"
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
                error="Прокси неисправен — проверка сессии пропущена",
            ),
            now=now,
        )

    geo_mismatch = countries_mismatch(proxy.country, snapshot.country)
    proxy_health = ProxyHealthStepOut(
        ok=True,
        ip=snapshot.ip,
        geo_country=snapshot.country,
        instagram_reachable=snapshot.instagram_reachable,
        geo_mismatch=geo_mismatch,
    )
    collector.info(
        "proxy_health",
        f"IP={snapshot.ip or 'неизвестен'}, страна={snapshot.country or 'неизвестна'}, "
        f"instagram_доступен={snapshot.instagram_reachable}",
    )
    if geo_mismatch:
        adv = normalize_country_code(proxy.country) or proxy.country
        act = normalize_country_code(snapshot.country) or snapshot.country
        collector.warn(
            "proxy_health",
            f"Несовпадение гео: указано {adv}, фактически {act}",
        )

    if health_error or not snapshot.instagram_reachable:
        err = health_error or "Instagram недоступен через прокси"
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

    collector.info("fingerprint", "Загрузка отпечатка устройства")
    fingerprint = ensure_fingerprint_and_proxy(
        username,
        country=normalize_country_code(proxy.country) or proxy.country or "US",
    )
    collector.info("session_probe", "Проверка сессии Instagram")
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
        error_code=probe.error_code,
        challenge=probe.challenge,
    )
    if probe.ok:
        collector.info(
            "session_probe",
            f"Авторизация через {probe.method}"
            + (f" как @{probe.ig_username}" if probe.ig_username else ""),
        )
    elif probe.challenge:
        collector.warn("session_probe", probe.error or "Требуется подтверждение")
    else:
        collector.error("session_probe", probe.error or "Проверка сессии не пройдена")

    overall_ok = proxy_health.ok and proxy_health.instagram_reachable and probe.ok
    summary = (
        "Готов к автопубликации"
        if overall_ok
        else (probe.error or health_error or "Проверка подключения не пройдена")
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
