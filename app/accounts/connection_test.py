"""Full account connection diagnostics: proxy health + session probe."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.accounts.account_diagnostics import log_account_credentials, proxy_log_line
from app.accounts.cookie_formats import STUDIO_PLATFORMS, studio_session_ready
from app.accounts.playwright_session import playwright_state_path
from app.accounts.device_factory import device_path
from app.accounts.session_cookie import normalize_sessionid, sessionid_diag_label
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
from app.geo.timezone_normalize import is_placeholder_timezone, timezone_from_proxy
from app.proxies.pool import ProxyError, health_check_record

_SESSION_SOURCE_LABEL: dict[str, str] = {
    "database": "БД",
    "session_file": "файл",
    "playwright": "Playwright",
    "none": "нет",
}


def _platform_value(account: Account) -> str:
    value = getattr(account, "platform", None)
    if hasattr(value, "value"):
        return value.value
    return value or "instagram"


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



def run_account_connection_test(
    account: Account,
    db: Session,
    *,
    probe_mobile: bool = False,
) -> AccountConnectionTestOut:
    """Run proxy + session diagnostics.

    By default only checks that cookies exist in storage (no mobile
    ``login_by_sessionid``). Pass ``probe_mobile=True`` for publish readiness.
    """
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
    platform = _platform_value(account)
    if platform in STUDIO_PLATFORMS:
        pw_exists = playwright_state_path(username, platform).exists()
        ready = studio_session_ready(username, platform)
        source: Literal["database", "session_file", "playwright", "none"] = (
            "playwright" if ready else "none"
        )
        has_cookies = ready
        session_storage = SessionStorageStepOut(
            has_session_id=False,
            session_file_exists=pw_exists,
            device_file_exists=device_exists,
            session_source=source,
        )
    else:
        source = _session_source(username, account.session_id)
        has_cookies = bool((account.session_id or "").strip()) or file_exists
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
    collector.info(
        "session_probe",
        f"Режим: {'mobile API probe' if probe_mobile else 'cookies-only (без mobile login_by_sessionid)'}",
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
    collector.info("proxy", proxy_log_line(proxy))

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
        instagram_login_reachable=snapshot.instagram_login_reachable,
        geo_mismatch=geo_mismatch,
    )
    collector.info(
        "proxy_health",
        f"IP={snapshot.ip or 'неизвестен'}, страна={snapshot.country or 'неизвестна'}, "
        f"instagram_доступен={snapshot.instagram_reachable}, "
        f"login_страница={snapshot.instagram_login_reachable}",
    )
    if geo_mismatch:
        adv = normalize_country_code(proxy.country) or proxy.country
        act = normalize_country_code(snapshot.country) or snapshot.country
        collector.warn(
            "proxy_health",
            f"Несовпадение гео: указано {adv}, фактически {act}",
        )

    if platform in STUDIO_PLATFORMS:
        if probe_mobile:
            err = "probe_mobile только для Instagram"
            collector.error("session_probe", err)
            return _finish(
                collector,
                overall_ok=False,
                summary=err,
                username=username,
                proxy_assigned=True,
                proxy_label=proxy_label,
                proxy_health=proxy_health,
                session_storage=session_storage,
                instagram_auth=InstagramAuthStepOut(ok=False, method="none", error=err),
                now=now,
            )
        collector.info(
            "session_probe",
            f"Площадка={platform}, Playwright state="
            f"{_yes_no(playwright_state_path(username, platform).exists())}, "
            f"cookies площадки={_yes_no(has_cookies)}",
        )
        if has_cookies:
            collector.info(
                "session_probe",
                "Cookies Studio на диске — живость на сервере не проверялась",
            )
            instagram_auth = InstagramAuthStepOut(ok=True, method="playwright")
            overall_ok = True
            summary = "Cookies Studio на диске (живость на сервере не проверялась)"
        else:
            err = (
                "Playwright state не найден — импортируйте cookies или сохраните сессию в браузере"
            )
            collector.error("session_probe", err)
            instagram_auth = InstagramAuthStepOut(
                ok=False,
                method="none",
                error=err,
                error_code="session_missing",
            )
            overall_ok = False
            summary = err
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

    sid_raw = (account.session_id or "").strip()
    sid_norm = normalize_sessionid(sid_raw) or ""
    collector.info(
        "session_probe",
        f"Хранилище: sessionid в БД="
        f"{'да (' + sessionid_diag_label(sid_norm) + ')' if sid_norm else 'нет'}, "
        f"файл session_*.json={'да' if file_exists else 'нет'}",
    )

    if not probe_mobile:
        if has_cookies:
            method: Literal["sessionid", "session_file", "none"] = (
                "sessionid" if sid_norm else "session_file"
            )
            collector.info(
                "session_probe",
                "Mobile API-проверка пропущена — cookie в хранилище достаточно для этого режима",
            )
            instagram_auth = InstagramAuthStepOut(ok=True, method=method)
            overall_ok = True
            summary = "Cookies установлены (mobile не проверялась)"
        else:
            collector.error(
                "session_probe",
                "Нет session_id в БД и нет файла сессии на диске",
            )
            instagram_auth = InstagramAuthStepOut(
                ok=False,
                method="none",
                error=(
                    "Нет session_id в БД и нет файла сессии на диске. "
                    "Импортируйте sessionid через панель «Сессия»."
                ),
                error_code="session_missing",
            )
            overall_ok = False
            summary = instagram_auth.error or "Сессия не найдена"
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

    collector.info("fingerprint", "Загрузка отпечатка устройства")
    tz_id = timezone_from_proxy(proxy.timezone, proxy.country)
    if is_placeholder_timezone(account.timezone):
        account.timezone = tz_id
        db.commit()
        collector.info("timezone", f"Часовой пояс аккаунта выставлен по прокси: {tz_id}")
    fingerprint = ensure_fingerprint_and_proxy(
        username,
        country=normalize_country_code(proxy.country) or proxy.country or "US",
        timezone_id=tz_id,
    )
    collector.info("session_probe", "Проверка сессии Instagram (mobile API)")
    try:
        probe = probe_session_auth(
            username=username,
            fingerprint=fingerprint,
            proxy_url=proxy.url,
            session_id=account.session_id,
            diag=collector.callback(),
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
