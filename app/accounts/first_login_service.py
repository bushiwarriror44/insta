"""API-facing Playwright first-login orchestration."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.accounts.connection_test import run_account_connection_test
from app.accounts.login_identifier import (
    is_account_not_found_error,
    resolve_login_identifier,
)
from app.accounts.playwright_session import (
    cookie_names_from_playwright_state,
    import_playwright_session_to_account,
    login_debug_screenshot_path,
)
from app.accounts.session_manager import (
    AuthenticationError,
    HardCheckpoint,
    ensure_fingerprint_and_proxy,
    login_and_export_sessionid,
)
from app.api.schemas import AccountConnectionTestOut, DiagnosticLogLineOut, FirstLoginOut
from app.behavior.warmup_playwright import FirstLoginResult, first_login, playwright_browsers_available
from app.db import Account, DiagnosticRunKind, Proxy
from app.diagnostics.collector import DiagnosticCollector
from app.geo.country_codes import normalize_country_code
from app.geo.timezone_normalize import normalize_playwright_timezone


def _format_auth_error(exc: AuthenticationError) -> str:
    msg = str(exc).strip().lower()
    if is_account_not_found_error(msg):
        return (
            "Instagram не находит аккаунт с этим логином — "
            "укажите email/телефон в поле «Логин Instagram»"
        )
    if "bad password" in msg:
        return "Неверный пароль — обновите пароль аккаунта в панели"
    if "2fa" in msg or "verification" in msg:
        return "Требуется 2FA — добавьте TOTP seed в настройках аккаунта"
    if "rate-limited" in msg:
        return "Instagram временно ограничил вход — повторите позже"
    return str(exc).strip() or "Ошибка аутентификации Instagram"


def _login_debug_available(username: str, result: FirstLoginResult | None = None) -> bool:
    if result is not None and result.login_debug_saved:
        return True
    return login_debug_screenshot_path(username).exists()


def _finish_success(
    collector: DiagnosticCollector,
    account: Account,
    db: Session,
    *,
    login_message: str,
) -> FirstLoginOut:
    collector.info("login", login_message)
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


def _api_login_session_id(
    account: Account,
    fingerprint,
    proxy: Proxy,
    *,
    login_identifier: str,
) -> str:
    return login_and_export_sessionid(
        account.username,
        account.password,
        fingerprint,
        proxy.url,
        totp_seed=account.totp_seed,
        login_identifier=login_identifier,
    )


def _try_api_login_fallback(
    collector: DiagnosticCollector,
    account: Account,
    db: Session,
    proxy: Proxy,
    fingerprint,
) -> tuple[FirstLoginOut | None, str | None]:
    collector.warn("fallback", "Браузерный вход не дал sessionid — пробуем Instagram API")
    login_id = resolve_login_identifier(account)
    session_id: str | None = None
    last_auth_error: AuthenticationError | None = None

    def _attempt(login_identifier: str) -> str:
        return _api_login_session_id(
            account, fingerprint, proxy, login_identifier=login_identifier
        )

    try:
        session_id = _attempt(login_id)
    except HardCheckpoint as exc:
        collector.warn("login", "Требуется ручное подтверждение (challenge)")
        collector.finish("warn", "challenge required")
        return (
            FirstLoginOut(
                run_id=collector.run_id,
                ok=False,
                challenge=True,
                error=str(exc) or "Требуется подтверждение Instagram",
                logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
            ),
            None,
        )
    except AuthenticationError as exc:
        last_auth_error = exc
    except Exception as exc:  # noqa: BLE001
        collector.error("fallback", f"API-вход не удался: {exc}")
        return None, str(exc)

    if session_id is None and last_auth_error is not None:
        email = (account.email or "").strip()
        if (
            is_account_not_found_error(str(last_auth_error))
            and email
            and email.lower() != login_id.lower()
        ):
            collector.info("fallback", "Повтор входа по email из настроек аккаунта")
            try:
                session_id = _attempt(email)
            except HardCheckpoint as exc:
                collector.warn("login", "Требуется ручное подтверждение (challenge)")
                collector.finish("warn", "challenge required")
                return (
                    FirstLoginOut(
                        run_id=collector.run_id,
                        ok=False,
                        challenge=True,
                        error=str(exc) or "Требуется подтверждение Instagram",
                        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
                    ),
                    None,
                )
            except AuthenticationError as exc:
                last_auth_error = exc
            except Exception as exc:  # noqa: BLE001
                collector.error("fallback", f"API-вход не удался: {exc}")
                return None, str(exc)

    if session_id is None:
        formatted = _format_auth_error(last_auth_error or AuthenticationError("auth failed"))
        collector.error("fallback", f"API-вход не удался: {formatted}")
        return None, formatted

    account.session_id = session_id
    db.commit()
    db.refresh(account)
    return (
        _finish_success(
            collector,
            account,
            db,
            login_message="Вход через Instagram API выполнен, sessionid получен",
        ),
        None,
    )


def _log_playwright_failure_diagnostics(
    collector: DiagnosticCollector,
    account: Account,
    result: FirstLoginResult,
) -> None:
    if result.page_url:
        collector.info("browser", f"URL после входа: {result.page_url}")
    if _login_debug_available(account.username, result):
        collector.info("browser", "Скриншот ошибки сохранён — см. ниже в модале")


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

    login_id = resolve_login_identifier(account)
    collector.info("start", f"Автовход через браузер для @{account.username}")
    if login_id.lower() != account.username.lower():
        collector.info("browser", f"Логин Instagram: {login_id}")
    collector.info("proxy", f"Прокси {proxy.label}")

    fingerprint = ensure_fingerprint_and_proxy(
        account.username,
        country=normalize_country_code(proxy.country) or proxy.country or "US",
    )
    collector.info("browser", "Запуск Playwright Chromium (desktop)")

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
        login_identifier=login_id,
    )

    if result.challenge:
        collector.warn("login", "Требуется ручное подтверждение (challenge)")
        _log_playwright_failure_diagnostics(collector, account, result)
        collector.finish("warn", "challenge required")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            challenge=True,
            error=result.error or "Требуется подтверждение Instagram",
            login_debug_available=_login_debug_available(account.username, result),
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not result.ok:
        msg = result.error or "Автовход не удался"
        collector.error("login", msg)
        _log_playwright_failure_diagnostics(collector, account, result)
        fallback_out, api_err = _try_api_login_fallback(collector, account, db, proxy, fingerprint)
        if fallback_out is not None:
            return fallback_out
        final_error = api_err or msg
        collector.finish("fail", final_error)
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error=final_error,
            login_debug_available=_login_debug_available(account.username, result),
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

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
        _log_playwright_failure_diagnostics(collector, account, result)
        fallback_out, api_err = _try_api_login_fallback(collector, account, db, proxy, fingerprint)
        if fallback_out is not None:
            return fallback_out
        collector.finish("fail", api_err or "session import failed")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error=api_err or "Не удалось извлечь sessionid из сохранённого состояния браузера",
            login_debug_available=_login_debug_available(account.username, result),
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    return _finish_success(
        collector,
        account,
        db,
        login_message="Браузерный вход выполнен, sessionid получен",
    )
