"""Connection method ladder + structured attempt logs."""

from __future__ import annotations

from app.accounts.connection_ladder import (
    METHOD_MOBILE_API,
    METHOD_PLAYWRIGHT,
    METHOD_VNC,
    ConnectionLadder,
)
from app.accounts.first_login_service import run_account_first_login
from app.accounts.studio_login_service import run_studio_login
from app.behavior.warmup_playwright import FirstLoginResult
from app.db.models import DiagnosticRunKind, Event, EventLevel
from app.diagnostics.collector import DiagnosticCollector, LOGIN_EVENT_KINDS


def test_collector_attempt_message_shape(db_session, make_account):
    account = make_account(username="att1")
    collector = DiagnosticCollector(
        db_session, kind=DiagnosticRunKind.first_login, account_id=account.id
    )
    collector.attempt(
        METHOD_PLAYWRIGHT,
        "fail",
        "timeout",
        error="no sessionid",
        next_method=METHOD_MOBILE_API,
    )
    line = collector.lines[-1]
    assert line.step == "attempt"
    assert line.level == "error"
    assert "method=playwright" in line.message
    assert "status=fail" in line.message
    assert "next=mobile_api" in line.message
    assert "error=no sessionid" in line.message


def test_studio_login_in_login_event_kinds():
    assert DiagnosticRunKind.studio_login in LOGIN_EVENT_KINDS


def test_ladder_summary_after_fallback():
    class _C:
        def attempt(self, *a, **k):
            return None

    ladder = ConnectionLadder(_C())  # type: ignore[arg-type]
    ladder.start(METHOD_PLAYWRIGHT, next_method=METHOD_MOBILE_API)
    ladder.fail(METHOD_PLAYWRIGHT, error="x", next_method=METHOD_MOBILE_API)
    ladder.start(METHOD_MOBILE_API)
    ladder.ok(METHOD_MOBILE_API)
    assert ladder.summary_ok() == "удалось на mobile_api после playwright"


def test_ig_playwright_fail_api_ok_skips_mint(
    db_session, make_account, make_proxy, monkeypatch
):
    proxy = make_proxy(label="px-ladder-api")
    account = make_account(username="ladderapi", proxy=proxy)
    mint_calls = {"n": 0}

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(ok=False, error="browser miss"),
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.login_and_export_sessionid",
        lambda *a, **k: "a" * 40,
    )

    def _mint(*a, **k):
        mint_calls["n"] += 1
        raise AssertionError("mint must not run when API succeeds")

    monkeypatch.setattr(
        "app.accounts.mint_mobile_session.mint_mobile_session_into",
        _mint,
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert mint_calls["n"] == 0
    attempts = [line for line in out.logs if line.step == "attempt"]
    assert any("method=playwright" in line.message and "status=fail" in line.message for line in attempts)
    assert any("method=mobile_api" in line.message and "status=ok" in line.message for line in attempts)
    assert not any("method=mint_mobile" in line.message and "status=started" in line.message for line in attempts)


def test_ig_playwright_and_api_fail_calls_mint(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.accounts.mint_mobile_session import MintCoreResult
    from app.accounts.session_manager import AuthenticationError

    proxy = make_proxy(label="px-ladder-mint")
    account = make_account(username="laddermint", proxy=proxy)
    mint_calls = {"n": 0}

    monkeypatch.setattr(
        "app.accounts.first_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.first_login",
        lambda **kwargs: FirstLoginResult(ok=False, error="browser miss"),
    )
    monkeypatch.setattr(
        "app.accounts.first_login_service.login_and_export_sessionid",
        lambda *a, **k: (_ for _ in ()).throw(AuthenticationError("rate-limited")),
    )

    def _mint(collector, account, db, **kwargs):
        mint_calls["n"] += 1
        account.session_id = "m" * 40
        db.commit()
        return MintCoreResult(ok=True, session_id="m" * 40)

    monkeypatch.setattr(
        "app.accounts.mint_mobile_session.mint_mobile_session_into",
        _mint,
    )

    out = run_account_first_login(account, db_session)
    assert out.ok is True
    assert mint_calls["n"] == 1
    assert any(
        line.step == "attempt"
        and "method=mint_mobile" in line.message
        and "status=ok" in line.message
        for line in out.logs
    )
    db_session.refresh(account)
    assert account.session_id == "m" * 40


def test_studio_headless_fail_calls_vnc(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.behavior.studio_playwright import StudioLoginResult

    proxy = make_proxy(label="px-vnc")
    account = make_account(username="vncyt", proxy=proxy, platform="youtube")
    account.password = "secret"
    db_session.commit()
    vnc_calls = {"n": 0}

    monkeypatch.setattr(
        "app.accounts.studio_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.studio_login_service.studio_session_ready",
        lambda u, p: False,
    )
    monkeypatch.setattr(
        "app.accounts.studio_login_service.studio_login",
        lambda **k: StudioLoginResult(ok=False, challenge=True, error="2fa"),
    )

    def _vnc(collector, account, db, proxy, *, on_status=None, ladder=None):
        vnc_calls["n"] += 1
        if ladder is not None:
            ladder.start(METHOD_VNC)
            ladder.ok(METHOD_VNC)
        from app.api.schemas import FirstLoginOut

        collector.finish("ok", ladder.summary_ok() if ladder else "ok")
        return FirstLoginOut(
            run_id=collector.run_id,
            ok=True,
            session_imported=True,
            logs=[],
        )

    monkeypatch.setattr(
        "app.accounts.studio_login_service._run_vnc_fallback",
        _vnc,
    )

    out = run_studio_login(account, db_session)
    assert out.ok is True
    assert vnc_calls["n"] == 1


def test_studio_login_fail_creates_event(db_session, make_account, make_proxy, monkeypatch):
    from app.behavior.studio_playwright import StudioLoginResult

    proxy = make_proxy(label="px-ev")
    account = make_account(username="evyt", proxy=proxy, platform="youtube")
    account.password = "secret"
    db_session.commit()

    monkeypatch.setattr(
        "app.accounts.studio_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.studio_login_service.studio_session_ready",
        lambda u, p: False,
    )
    monkeypatch.setattr(
        "app.accounts.studio_login_service.studio_login",
        lambda **k: StudioLoginResult(ok=False, error="hard fail"),
    )
    monkeypatch.setattr(
        "app.accounts.studio_login_service._run_vnc_fallback",
        lambda collector, account, db, proxy, **k: (
            collector.finish("fail", "VNC тоже нет"),
            __import__("app.api.schemas", fromlist=["FirstLoginOut"]).FirstLoginOut(
                run_id=collector.run_id,
                ok=False,
                error="VNC тоже нет",
                logs=[],
            ),
        )[1],
    )

    out = run_studio_login(account, db_session)
    assert out.ok is False
    events = (
        db_session.query(Event)
        .filter(Event.account_id == account.id, Event.kind == "studio_login")
        .all()
    )
    assert len(events) >= 1
    assert events[0].level == EventLevel.error
