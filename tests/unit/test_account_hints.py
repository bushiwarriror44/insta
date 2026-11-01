"""Tests for app.accounts.account_hints."""
from __future__ import annotations

from datetime import datetime, timezone

from app.accounts.account_hints import hint_for_connection_test, hint_for_first_login
from app.api.schemas import (
    AccountConnectionTestOut,
    DiagnosticLogLineOut,
    FirstLoginOut,
    InstagramAuthStepOut,
    ProxyHealthStepOut,
    SessionStorageStepOut,
)
from app.db.models import Account, Platform


def _account(**kwargs) -> Account:
    base = dict(username="alice", platform=Platform.instagram, proxy_id=1)
    base.update(kwargs)
    return Account(**base)


def test_hint_imap_auth_failure_on_challenge():
    out = FirstLoginOut(
        run_id=1,
        ok=False,
        challenge=True,
        error="challenge timeout",
        logs=[
            DiagnosticLogLineOut(
                ts="2026-01-01T00:00:00Z",
                level="warn",
                step="email",
                message="email.imap_error AUTHENTICATIONFAILED",
            )
        ],
    )
    hint = hint_for_first_login(out, _account())
    assert hint is not None
    assert hint.severity == "warn"
    assert "почт" in hint.message.lower() or "IMAP" in hint.message
    assert any("email_password" in s.lower() or "пароль почты" in s.lower() for s in hint.steps)


def test_hint_login_form_not_found():
    out = FirstLoginOut(
        run_id=1,
        ok=False,
        error="поля формы входа не найдены (url='https://www.instagram.com/accounts/login/')",
    )
    hint = hint_for_first_login(out, _account())
    assert hint is not None
    assert "браузер" in hint.message.lower() or "браузер" in " ".join(hint.steps).lower()


def test_hint_challenge_timeout_precedence():
    out = FirstLoginOut(
        run_id=1,
        ok=False,
        challenge=False,
        error="wait",
        logs=[
            DiagnosticLogLineOut(
                ts="2026-01-01T00:00:00Z",
                level="warn",
                step="challenge",
                message="challenge.timeout истёк",
            )
        ],
    )
    hint = hint_for_first_login(out, _account())
    assert hint is not None
    assert "вовремя" in hint.title.lower() or "вовремя" in hint.message.lower()


def test_hint_please_wait_few_minutes():
    out = FirstLoginOut(
        run_id=1,
        ok=False,
        error="PleaseWaitFewMinutes: try again later",
    )
    hint = hint_for_first_login(out, _account())
    assert hint is not None
    assert hint.severity == "info"
    assert "подожд" in hint.title.lower() or "подожд" in hint.message.lower()


def test_hint_playwright_not_installed():
    out = FirstLoginOut(
        run_id=1,
        ok=False,
        logs=[
            DiagnosticLogLineOut(
                ts="2026-01-01T00:00:00Z",
                level="error",
                step="playwright",
                message="Chromium не установлен — install-playwright",
            )
        ],
    )
    hint = hint_for_first_login(out, _account())
    assert hint is not None
    assert hint.action_key == "install_playwright"


def test_hint_connection_session_missing():
    now = datetime.now(timezone.utc)
    out = AccountConnectionTestOut(
        username="alice",
        proxy_assigned=True,
        proxy_label="p1",
        proxy_health=ProxyHealthStepOut(ok=True, geo_mismatch=False),
        session_storage=SessionStorageStepOut(
            has_session_id=False,
            session_file_exists=False,
            device_file_exists=True,
            session_source="none",
        ),
        instagram_auth=InstagramAuthStepOut(
            ok=False,
            method="none",
            error="нет session_id",
            error_code="session_missing",
        ),
        overall_ok=False,
        checked_at=now,
        run_id=2,
    )
    hint = hint_for_connection_test(out, _account())
    assert hint is not None
    assert hint.severity == "info"
    assert "сесс" in hint.title.lower() or "сесс" in hint.message.lower()


def test_hint_connection_challenge_required():
    now = datetime.now(timezone.utc)
    out = AccountConnectionTestOut(
        username="alice",
        proxy_assigned=True,
        proxy_label="p1",
        proxy_health=ProxyHealthStepOut(ok=True, geo_mismatch=False),
        session_storage=SessionStorageStepOut(
            has_session_id=True,
            session_file_exists=True,
            device_file_exists=True,
            session_source="database",
        ),
        instagram_auth=InstagramAuthStepOut(
            ok=False,
            method="sessionid",
            error="ChallengeRequired",
            error_code="challenge_required",
        ),
        overall_ok=False,
        checked_at=now,
        run_id=4,
    )
    hint = hint_for_connection_test(out, _account())
    assert hint is not None
    assert hint.severity == "warn"
    assert "проверк" in hint.title.lower()


def test_hint_connection_rate_limited():
    now = datetime.now(timezone.utc)
    out = AccountConnectionTestOut(
        username="alice",
        proxy_assigned=True,
        proxy_label="p1",
        proxy_health=ProxyHealthStepOut(ok=True, geo_mismatch=False),
        session_storage=SessionStorageStepOut(
            has_session_id=True,
            session_file_exists=True,
            device_file_exists=True,
            session_source="database",
        ),
        instagram_auth=InstagramAuthStepOut(
            ok=False,
            method="sessionid",
            error="Please wait a few minutes before you try again.",
            error_code=None,
        ),
        overall_ok=False,
        checked_at=now,
        run_id=5,
    )
    hint = hint_for_connection_test(out, _account())
    assert hint is not None
    assert hint.severity == "info"
    assert "част" in hint.title.lower() or "минут" in " ".join(hint.steps).lower()


def test_hint_geo_mismatch_warn_when_overall_ok():
    now = datetime.now(timezone.utc)
    out = AccountConnectionTestOut(
        username="alice",
        proxy_assigned=True,
        proxy_label="p1",
        proxy_health=ProxyHealthStepOut(ok=True, geo_mismatch=True, geo_country="RU"),
        session_storage=SessionStorageStepOut(
            has_session_id=True,
            session_file_exists=False,
            device_file_exists=True,
            session_source="database",
        ),
        instagram_auth=InstagramAuthStepOut(ok=True, method="sessionid"),
        overall_ok=True,
        checked_at=now,
        run_id=3,
    )
    hint = hint_for_connection_test(out, _account())
    assert hint is not None
    assert hint.severity == "warn"


def test_hint_studio_liveness_stale_while_overall_ok():
    now = datetime.now(timezone.utc)
    out = AccountConnectionTestOut(
        username="yt1",
        proxy_assigned=True,
        proxy_label="p1",
        proxy_health=ProxyHealthStepOut(ok=True, geo_mismatch=False),
        session_storage=SessionStorageStepOut(
            has_session_id=False,
            session_file_exists=True,
            device_file_exists=False,
            session_source="playwright",
        ),
        instagram_auth=InstagramAuthStepOut(ok=True, method="playwright"),
        overall_ok=True,
        checked_at=now,
        run_id=6,
        studio_liveness_ok=False,
        studio_liveness_error="Cookies на диске есть, но Studio перенаправил на вход",
    )
    hint = hint_for_connection_test(out, _account(username="yt1", platform=Platform.youtube))
    assert hint is not None
    assert hint.severity == "warn"
    assert "cookies" in hint.title.lower() or "устар" in hint.title.lower()
