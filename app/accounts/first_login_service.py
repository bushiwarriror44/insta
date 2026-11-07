"""API-facing Playwright first-login orchestration."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.accounts.account_diagnostics import log_account_credentials, proxy_log_line
from app.accounts.connection_ladder import (
    METHOD_MINT_MOBILE,
    METHOD_MOBILE_API,
    METHOD_PLAYWRIGHT,
    METHOD_REUSE,
    ConnectionLadder,
)
from app.accounts.login_identifier import (
    is_account_not_found_error,
    resolve_login_identifier,
)
from app.accounts.playwright_session import (
    cookie_names_from_playwright_state,
    import_playwright_session_to_account,
    login_debug_screenshot_path,
    storage_state_has_session,
)
from app.accounts.session_manager import (
    AuthenticationError,
    HardCheckpoint,
    ensure_fingerprint_and_proxy,
    login_and_export_sessionid,
)
from app.api.schemas import DiagnosticLogLineOut, FirstLoginOut
from app.behavior.warmup_playwright import FirstLoginResult, first_login, playwright_browsers_available
from app.behavior.playwright_surface import resolve_playwright_surface, surface_label
from app.db import Account, DiagnosticRunKind, Proxy
from app.diagnostics.collector import DiagnosticCollector
from app.geo.country_codes import normalize_country_code
from app.geo.timezone_normalize import (
    is_placeholder_timezone,
    timezone_from_proxy,
)

CHALLENGE_SUMMARY = "Требуется подтверждение Instagram"
NO_PASSWORD_SUMMARY = "Пароль аккаунта не задан"
PROXY_MISSING_SUMMARY = "Запись прокси отсутствует"
PLAYWRIGHT_UNAVAILABLE_SUMMARY = (
    "Chromium не установлен — выполните install-playwright на сервере"
)


def _challenge_code_file(username: str) -> str:
    from app.accounts.challenge import challenge_code_display_path

    return challenge_code_display_path(username)


def _format_auth_error(exc: AuthenticationError) -> str:
    msg = str(exc).strip().lower()
    if is_account_not_found_error(msg):
        return (
            "Instagram не находит аккаунт с этим логином — "
            "укажите email/телефон в поле «Логин Instagram»"
        )
    if "bad password" in msg or "неверный пароль" in msg:
        return "Неверный пароль — обновите пароль аккаунта в панели"
    if "2fa" in msg or "verification" in msg or "код 2fa" in msg:
        return "Требуется 2FA — добавьте TOTP seed в настройках аккаунта"
    if "rate-limited" in msg or "временно ограничил" in msg:
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
    summary: str | None = None,
) -> FirstLoginOut:
    collector.info("login", login_message)
    collector.info("import", "sessionid сохранён в БД")
    db.refresh(account)
    # Do not run mobile login_by_sessionid here — it often burns the web cookie.
    collector.info(
        "verify",
        "Web-сессия сохранена; mobile API-проверка пропущена "
        "(чтобы не инвалидировать sessionid). При необходимости проверьте подключение отдельно.",
    )
    collector.finish("ok", summary or "Сессия создана")
    return FirstLoginOut(
        run_id=collector.run_id,
        ok=True,
        session_imported=True,
        connection_test=None,
        error=None,
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
    )


def _try_mint_fallback(
    ladder: ConnectionLadder,
    collector: DiagnosticCollector,
    account: Account,
    db: Session,
    proxy: Proxy,
    fingerprint,
) -> FirstLoginOut | None:
    if not (account.password or "").strip():
        ladder.skip(METHOD_MINT_MOBILE, "пароль не задан")
        return None
    ladder.start(METHOD_MINT_MOBILE, "password → mobile session dump")
    from app.accounts.mint_mobile_session import mint_mobile_session_into

    mint = mint_mobile_session_into(
        collector,
        account,
        db,
        proxy=proxy,
        fingerprint=fingerprint,
        log_preamble=False,
    )
    if mint.ok:
        ladder.ok(METHOD_MINT_MOBILE, "mobile sessionid сохранён")
        return _finish_success(
            collector,
            account,
            db,
            login_message="Вход через mint mobile выполнен, sessionid получен",
            summary=ladder.summary_ok(),
        )
    if mint.challenge:
        ladder.fail(METHOD_MINT_MOBILE, error=mint.error or "challenge")
        collector.finish("warn", CHALLENGE_SUMMARY)
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            challenge=True,
            browser_tab_hint=True,
            challenge_code_file=_challenge_code_file(account.username),
            error=mint.error or "Требуется подтверждение Instagram",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )
    ladder.fail(METHOD_MINT_MOBILE, error=mint.error)
    return None


def _api_login_session_id(
    account: Account,
    fingerprint,
    proxy: Proxy,
    *,
    login_identifier: str,
) -> str:
    from app.accounts.challenge import make_handler

    handler = make_handler(
        account.username,
        email=(account.email or "").strip() or None,
        email_password=(account.email_password or "").strip() or None,
        imap_host=(account.imap_host or "").strip() or None,
    )
    return login_and_export_sessionid(
        account.username,
        account.password,
        fingerprint,
        proxy.url,
        totp_seed=account.totp_seed,
        login_identifier=login_identifier,
        challenge_handler=handler,
    )


def _try_api_login_fallback(
    collector: DiagnosticCollector,
    account: Account,
    db: Session,
    proxy: Proxy,
    fingerprint,
    *,
    ladder: ConnectionLadder | None = None,
) -> tuple[FirstLoginOut | None, str | None]:
    next_method = (
        METHOD_MINT_MOBILE if (account.password or "").strip() else None
    )
    if ladder is not None:
        ladder.start(
            METHOD_MOBILE_API,
            "браузер не дал sessionid",
            next_method=next_method,
        )
    else:
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
        if ladder is not None:
            ladder.fail(METHOD_MOBILE_API, error=str(exc) or "challenge")
        collector.warn("login", "Требуется ручное подтверждение (challenge) — откройте вкладку «Браузер»")
        collector.finish("warn", CHALLENGE_SUMMARY)
        return (
            FirstLoginOut(
                run_id=collector.run_id,
                ok=False,
                challenge=True,
                browser_tab_hint=True,
                challenge_code_file=_challenge_code_file(account.username),
                error=str(exc) or "Требуется подтверждение Instagram",
                logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
            ),
            None,
        )
    except AuthenticationError as exc:
        last_auth_error = exc
    except Exception as exc:  # noqa: BLE001
        if ladder is not None:
            ladder.fail(METHOD_MOBILE_API, error=str(exc), next_method=next_method)
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
                if ladder is not None:
                    ladder.fail(METHOD_MOBILE_API, error=str(exc) or "challenge")
                collector.warn("login", "Требуется ручное подтверждение (challenge) — откройте вкладку «Браузер»")
                collector.finish("warn", CHALLENGE_SUMMARY)
                return (
                    FirstLoginOut(
                        run_id=collector.run_id,
                        ok=False,
                        challenge=True,
                        browser_tab_hint=True,
                        challenge_code_file=_challenge_code_file(account.username),
                        error=str(exc) or "Требуется подтверждение Instagram",
                        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
                    ),
                    None,
                )
            except AuthenticationError as exc:
                last_auth_error = exc
            except Exception as exc:  # noqa: BLE001
                if ladder is not None:
                    ladder.fail(METHOD_MOBILE_API, error=str(exc), next_method=next_method)
                collector.error("fallback", f"API-вход не удался: {exc}")
                return None, str(exc)

    if session_id is None:
        formatted = _format_auth_error(
            last_auth_error or AuthenticationError("ошибка аутентификации")
        )
        if ladder is not None:
            ladder.fail(METHOD_MOBILE_API, error=formatted, next_method=next_method)
        collector.error("fallback", f"API-вход не удался: {formatted}")
        return None, formatted

    account.session_id = session_id
    db.commit()
    db.refresh(account)
    if ladder is not None:
        ladder.ok(METHOD_MOBILE_API, "sessionid из Instagram API")
    return (
        _finish_success(
            collector,
            account,
            db,
            login_message="Вход через Instagram API выполнен, sessionid получен",
            summary=ladder.summary_ok() if ladder is not None else None,
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


def _after_playwright_miss(
    ladder: ConnectionLadder,
    collector: DiagnosticCollector,
    account: Account,
    db: Session,
    proxy: Proxy,
    fingerprint,
    *,
    browser_error: str,
    login_debug: bool,
    on_status=None,
) -> FirstLoginOut:
    if on_status:
        on_status("API", "браузер не дал sessionid — mobile API")
    fallback_out, api_err = _try_api_login_fallback(
        collector, account, db, proxy, fingerprint, ladder=ladder
    )
    if fallback_out is not None:
        return fallback_out
    mint_out = _try_mint_fallback(ladder, collector, account, db, proxy, fingerprint)
    if mint_out is not None:
        return mint_out
    final_error = api_err or browser_error
    if api_err and "Неверный пароль" in api_err:
        final_error = api_err
    collector.finish("fail", ladder.summary_fail(final_error))
    return FirstLoginOut(
        run_id=collector.run_id,
        ok=False,
        error=final_error,
        login_debug_available=login_debug,
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
    )


def run_account_first_login(
    account: Account,
    db: Session,
    *,
    surface: str | None = None,
    on_status=None,
) -> FirstLoginOut:
    collector = DiagnosticCollector(
        db,
        kind=DiagnosticRunKind.first_login,
        account_id=account.id,
    )
    ladder = ConnectionLadder(collector)

    if not playwright_browsers_available():
        collector.error("browser", PLAYWRIGHT_UNAVAILABLE_SUMMARY)
        collector.finish("fail", PLAYWRIGHT_UNAVAILABLE_SUMMARY)
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error=PLAYWRIGHT_UNAVAILABLE_SUMMARY,
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not account.proxy_id:
        collector.error("proxy", "Прокси не назначен")
        collector.finish("fail", "Прокси не назначен")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error="Прокси не назначен",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        collector.error("proxy", PROXY_MISSING_SUMMARY)
        collector.finish("fail", PROXY_MISSING_SUMMARY)
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error=PROXY_MISSING_SUMMARY,
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not (account.password or "").strip():
        collector.error("account", NO_PASSWORD_SUMMARY)
        collector.finish("fail", NO_PASSWORD_SUMMARY)
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            error=NO_PASSWORD_SUMMARY,
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    has_db_session = bool((account.session_id or "").strip())
    has_browser_session = storage_state_has_session(account.username)
    if has_db_session or has_browser_session:
        ladder.start(METHOD_REUSE, "sessionid в БД или Playwright state")
        if has_browser_session and not has_db_session:
            import_playwright_session_to_account(db, account)
            db.refresh(account)
        ladder.ok(METHOD_REUSE, "сессия уже сохранена")
        collector.info("session", "Сессия уже сохранена — повторный автовход не нужен")
        return _finish_success(
            collector,
            account,
            db,
            login_message="Используется сохранённая сессия",
            summary=ladder.summary_ok(),
        )

    resolved_surface = resolve_playwright_surface(surface or account.login_surface)
    account.login_surface = resolved_surface
    db.commit()

    login_id = resolve_login_identifier(account)
    log_account_credentials(collector, account, proxy)
    if on_status:
        on_status("Автовход", f"@{account.username} через браузер")
    collector.info("start", f"Автовход через браузер для @{account.username}")
    collector.info("proxy", proxy_log_line(proxy))

    tz_id = timezone_from_proxy(proxy.timezone, proxy.country)
    if is_placeholder_timezone(account.timezone):
        account.timezone = tz_id
        db.commit()
        collector.info("timezone", f"Часовой пояс аккаунта выставлен по прокси: {tz_id}")

    fingerprint = ensure_fingerprint_and_proxy(
        account.username,
        country=normalize_country_code(proxy.country) or proxy.country or "US",
        timezone_id=tz_id,
    )
    ladder.start(
        METHOD_PLAYWRIGHT,
        surface_label(resolved_surface),
        next_method=METHOD_MOBILE_API,
    )
    collector.info("browser", f"Запуск Playwright Chromium ({surface_label(resolved_surface)})")

    if tz_id != (proxy.timezone or "").strip():
        collector.info(
            "browser",
            f"Часовой пояс прокси «{proxy.timezone}» заменён на {tz_id} (Playwright требует IANA)",
        )

    if on_status:
        on_status("Браузер", "логин и проверка challenge")
    result: FirstLoginResult = first_login(
        username=account.username,
        password=account.password,
        proxy_url=proxy.url,
        timezone_id=tz_id,
        fingerprint=fingerprint,
        totp_seed=account.totp_seed,
        login_identifier=login_id,
        surface=resolved_surface,
        email=account.email,
        email_password=account.email_password,
        imap_host=account.imap_host,
        proxy_country=proxy.country,
    )

    if result.challenge:
        ladder.fail(METHOD_PLAYWRIGHT, error=result.error or "challenge", next_method=None)
        hint = "Требуется подтверждение — submit_login_code, затем login_account с verification_code"
        if (account.email or "").strip() and (account.email_password or "").strip():
            from app.accounts.email_handler import imap_configuration_error

            imap_err = imap_configuration_error(
                account.email or "",
                (account.imap_host or "").strip() or None,
            )
            if imap_err:
                hint = f"{hint}. IMAP: {imap_err}"
            else:
                hint = (
                    "Код из почты не пришёл вовремя — submit_login_code, "
                    "затем login_account с verification_code"
                )
        collector.warn("login", hint)
        _log_playwright_failure_diagnostics(collector, account, result)
        collector.finish("warn", CHALLENGE_SUMMARY)
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=False,
            challenge=True,
            browser_tab_hint=True,
            challenge_code_file=_challenge_code_file(account.username),
            error=result.error or "Требуется подтверждение Instagram",
            login_debug_available=_login_debug_available(account.username, result),
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not result.ok:
        msg = result.error or "Автовход не удался"
        ladder.fail(METHOD_PLAYWRIGHT, error=msg, next_method=METHOD_MOBILE_API)
        collector.error("login", msg)
        _log_playwright_failure_diagnostics(collector, account, result)
        return _after_playwright_miss(
            ladder,
            collector,
            account,
            db,
            proxy,
            fingerprint,
            browser_error=msg,
            login_debug=_login_debug_available(account.username, result),
            on_status=on_status,
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
            import_err = (
                f"Не удалось извлечь sessionid из Playwright state; cookies: {preview}{suffix}"
            )
        else:
            import_err = "Не удалось извлечь sessionid из Playwright state (файл пуст или отсутствует)"
        collector.error("import", import_err)
        ladder.fail(METHOD_PLAYWRIGHT, error=import_err, next_method=METHOD_MOBILE_API)
        _log_playwright_failure_diagnostics(collector, account, result)
        return _after_playwright_miss(
            ladder,
            collector,
            account,
            db,
            proxy,
            fingerprint,
            browser_error=import_err,
            login_debug=_login_debug_available(account.username, result),
            on_status=on_status,
        )

    ladder.ok(METHOD_PLAYWRIGHT, "sessionid из Playwright")
    return _finish_success(
        collector,
        account,
        db,
        login_message="Браузерный вход выполнен, sessionid получен",
        summary=ladder.summary_ok(),
    )
