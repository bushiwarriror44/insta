"""API-facing Playwright first-login orchestration."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.accounts.connection_test import run_account_connection_test
from app.accounts.playwright_session import (
    cookie_names_from_playwright_state,
    import_playwright_session_to_account,
)
from app.accounts.session_manager import ensure_fingerprint_and_proxy
from app.api.schemas import AccountConnectionTestOut, DiagnosticLogLineOut, FirstLoginOut
from app.behavior.warmup_playwright import FirstLoginResult, first_login, playwright_browsers_available
from app.db import Account, DiagnosticRunKind, Proxy
from app.diagnostics.collector import DiagnosticCollector
from app.geo.country_codes import normalize_country_code
from app.geo.timezone_normalize import normalize_playwright_timezone


def run_account_first_login(account: Account, db: Session) -> FirstLoginOut:
    collector = DiagnosticCollector(
        db,
        kind=DiagnosticRunKind.first_login,
        account_id=account.id,
    )

    if not playwright_browsers_available():
        collector.error("browser", "Chromium не установлен — выполните install-playwright на сервере")
        collector.finish("fail", "playwright unavailable")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error="Chromium не установлен — выполните install-playwright на сервере",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not account.proxy_id:
        collector.error("proxy", "Прокси не назначен")
        collector.finish("fail", "no proxy")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error="Прокси не назначен",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        collector.error("proxy", "Запись прокси отсутствует")
        collector.finish("fail", "proxy missing")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error="Запись прокси отсутствует",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not (account.password or "").strip():
        collector.error("account", "Пароль аккаунта не задан")
        collector.finish("fail", "no password")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error="Пароль аккаунта не задан",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    collector.info("start", f"Автовход через браузер для @{account.username}")
    collector.info("proxy", f"Прокси {proxy.label}")

    fingerprint = ensure_fingerprint_and_proxy(
        account.username,
        country=normalize_country_code(proxy.country) or proxy.country or "US",
    )
    collector.info("browser", "Запуск Playwright Chromium")

    tz_id = normalize_playwright_timezone(proxy.timezone, country=proxy.country)
    if tz_id != (proxy.timezone or "").strip():
        collector.info(
            "browser",
            f"Часовой пояс прокси «{proxy.timezone}» заменён на {tz_id} (Playwright требует IANA)",
        )

    result: FirstLoginResult = first_login(
        username=account.username,
        password=account.password,
        proxy_url=proxy.url,
        timezone_id=tz_id,
        fingerprint=fingerprint,
        totp_seed=account.totp_seed,
    )

    if result.challenge:
        collector.warn("login", "Требуется ручное подтверждение (challenge)")
        collector.finish("warn", "challenge required")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            challenge=True,
            error=result.error or "Требуется подтверждение Instagram",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not result.ok:
        collector.error("login", result.error or "Автовход не удался")
        collector.finish("fail", result.error or "login failed")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error=result.error or "Автовход не удался",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    collector.info("login", "Браузерный вход выполнен, sessionid получен")

    session_imported = import_playwright_session_to_account(
        db,
        account,
        session_id=result.session_id,
    )
    if not session_imported:
        names = cookie_names_from_playwright_state(account.username)
        if names:
            preview = ", ".join(names[:12])
            suffix = f" ({len(names)} шт.)" if len(names) > 12 else ""
            collector.error(
                "import",
                f"Не удалось извлечь sessionid из Playwright state; cookies: {preview}{suffix}",
            )
        else:
            collector.error("import", "Не удалось извлечь sessionid из Playwright state (файл пуст или отсутствует)")
        collector.finish("fail", "session import failed")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error="Не удалось извлечь sessionid из сохранённого состояния браузера",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    collector.info("import", "sessionid сохранён в БД")
    db.refresh(account)

    collector.info("verify", "Повторная проверка подключения")
    connection_test: AccountConnectionTestOut = run_account_connection_test(account, db)

    overall_ok = connection_test.overall_ok
    if overall_ok:
        collector.finish("ok", "Сессия создана и проверена")
    else:
        err = connection_test.instagram_auth.error or "Проверка подключения не пройдена"
        collector.finish("fail", err)

    return FirstLoginOut(
        run_id=collector.run_id,
        ok=overall_ok,
        session_imported=True,
        connection_test=connection_test,
        error=None if overall_ok else (connection_test.instagram_auth.error or "Проверка не пройдена"),
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
    )
