"""Mint a mobile (instagrapi) session for publish via password login."""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.accounts.account_diagnostics import log_account_credentials, proxy_log_line
from app.accounts.challenge import make_handler
from app.accounts.first_login_service import _format_auth_error
from app.accounts.login_identifier import (
    is_account_not_found_error,
    resolve_login_identifier,
)
from app.accounts.session_cookie import sessionid_diag_label
from app.accounts.session_manager import (
    AuthenticationError,
    HardCheckpoint,
    ensure_fingerprint_and_proxy,
    login_and_export_sessionid,
)
from app.api.schemas import DiagnosticLogLineOut, MintMobileSessionOut
from app.db import Account, AccountStatus, DiagnosticRunKind, Proxy
from app.diagnostics.collector import DiagnosticCollector
from app.geo.country_codes import normalize_country_code
from app.geo.timezone_normalize import (
    is_placeholder_timezone,
    timezone_from_proxy,
)


def mint_mobile_session(account: Account, db: Session) -> MintMobileSessionOut:
    """Password-login via mobile API, dump session file, store sessionid in DB."""
    collector = DiagnosticCollector(
        db,
        kind=DiagnosticRunKind.mint_mobile_session,
        account_id=account.id,
    )
    started = time.monotonic()

    def _elapsed() -> str:
        return f"elapsed_ms={int((time.monotonic() - started) * 1000)}"

    if not account.proxy_id:
        collector.error("proxy", "Прокси не назначен")
        collector.finish("fail", "Прокси не назначен")
        return MintMobileSessionOut(
            run_id=collector.run_id,
            ok=False,
            error="Прокси не назначен",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        collector.error("proxy", "Запись прокси отсутствует")
        collector.finish("fail", "Запись прокси отсутствует")
        return MintMobileSessionOut(
            run_id=collector.run_id,
            ok=False,
            error="Запись прокси отсутствует",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if not (account.password or "").strip():
        collector.error("account", "Пароль аккаунта не задан")
        collector.finish("fail", "Пароль аккаунта не задан")
        return MintMobileSessionOut(
            run_id=collector.run_id,
            ok=False,
            error="Пароль аккаунта не задан — укажите пароль в настройках аккаунта",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    log_account_credentials(collector, account, proxy)
    collector.info("start", f"Создание mobile-сессии для @{account.username}")
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
    collector.info("fingerprint", "Отпечаток устройства готов")

    login_id = resolve_login_identifier(account)
    collector.info("mint", f"login_identifier={login_id}")
    handler = make_handler(
        account.username,
        email=(account.email or "").strip() or None,
        email_password=(account.email_password or "").strip() or None,
        imap_host=(account.imap_host or "").strip() or None,
    )

    def _attempt(login_identifier: str) -> str:
        collector.info("login", f"Мобильный вход как {login_identifier}")
        return login_and_export_sessionid(
            account.username,
            account.password,
            fingerprint,
            proxy.url,
            totp_seed=account.totp_seed,
            login_identifier=login_identifier,
            challenge_handler=handler,
        )

    session_id: str | None = None
    last_auth_error: AuthenticationError | None = None

    try:
        session_id = _attempt(login_id)
    except HardCheckpoint as exc:
        collector.warn("login", f"Требуется подтверждение Instagram (challenge); {_elapsed()}")
        collector.finish("warn", "Требуется подтверждение Instagram")
        return MintMobileSessionOut(
            run_id=collector.run_id,
            ok=False,
            challenge=True,
            error=str(exc) or "Требуется подтверждение Instagram",
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )
    except AuthenticationError as exc:
        last_auth_error = exc
    except Exception as exc:  # noqa: BLE001
        collector.error("login", f"Мобильный вход не удался: {exc}; {_elapsed()}")
        collector.finish("fail", "Вход не удался")
        return MintMobileSessionOut(
            run_id=collector.run_id,
            ok=False,
            error=str(exc),
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    if session_id is None and last_auth_error is not None:
        email = (account.email or "").strip()
        if (
            is_account_not_found_error(str(last_auth_error))
            and email
            and email.lower() != login_id.lower()
        ):
            collector.info("login", "Повтор входа по email из настроек аккаунта")
            try:
                session_id = _attempt(email)
            except HardCheckpoint as exc:
                collector.warn(
                    "login",
                    f"Требуется подтверждение Instagram (challenge); {_elapsed()}",
                )
                collector.finish("warn", "Требуется подтверждение Instagram")
                return MintMobileSessionOut(
                    run_id=collector.run_id,
                    ok=False,
                    challenge=True,
                    error=str(exc) or "Требуется подтверждение Instagram",
                    logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
                )
            except AuthenticationError as exc:
                last_auth_error = exc
            except Exception as exc:  # noqa: BLE001
                collector.error("login", f"Мобильный вход не удался: {exc}; {_elapsed()}")
                collector.finish("fail", "Вход не удался")
                return MintMobileSessionOut(
                    run_id=collector.run_id,
                    ok=False,
                    error=str(exc),
                    logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
                )

    if session_id is None:
        formatted = _format_auth_error(
            last_auth_error or AuthenticationError("ошибка аутентификации")
        )
        collector.error("login", f"Мобильный вход не удался: {formatted}; {_elapsed()}")
        collector.finish("fail", formatted)
        return MintMobileSessionOut(
            run_id=collector.run_id,
            ok=False,
            error=formatted,
            logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
        )

    account.session_id = session_id
    account.status = AccountStatus.active
    db.commit()
    db.refresh(account)

    collector.info(
        "session",
        f"Мобильный sessionid сохранён ({sessionid_diag_label(session_id)}); {_elapsed()}",
    )
    collector.finish("ok", "Mobile-сессия готова к автопостингу")
    return MintMobileSessionOut(
        run_id=collector.run_id,
        ok=True,
        session_id=session_id,
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in collector.lines],
    )
