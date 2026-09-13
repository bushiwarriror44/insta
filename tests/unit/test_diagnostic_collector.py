"""Tests for diagnostic log collector."""
from __future__ import annotations

from app.accounts.account_diagnostics import proxy_endpoint
from app.db import Account, DiagnosticRun, DiagnosticRunKind, DiagnosticRunStatus
from app.diagnostics.collector import DiagnosticCollector, load_run_lines


def test_proxy_endpoint_strips_userinfo():
    assert proxy_endpoint("http://u:p@host:8000") == "host:8000"
    assert proxy_endpoint("socks5://egress.example:1080") == "egress.example:1080"
    assert proxy_endpoint("http://only-host") == "only-host"
    assert proxy_endpoint("") == ""
    assert proxy_endpoint(None) == ""


def _make_account(db_session, username="diaguser"):
    account = Account(username=username, password="secret")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def test_collector_writes_lines_and_finishes(db_session):
    account = _make_account(db_session)
    collector = DiagnosticCollector(
        db_session,
        kind=DiagnosticRunKind.connection_test,
        account_id=account.id,
    )
    collector.info("proxy", "Proxy assigned")
    collector.warn("session", "No session yet")
    collector.finish("warn", "Not ready")

    run = db_session.get(DiagnosticRun, collector.run_id)
    assert run is not None
    assert run.status == DiagnosticRunStatus.warn
    assert run.summary == "Not ready"
    assert run.finished_at is not None

    lines = load_run_lines(run)
    assert len(lines) == 2
    assert lines[0].step == "proxy"
    assert lines[1].level == "warn"


def test_callback_adapter(db_session):
    account = _make_account(db_session, username="cbuser")
    collector = DiagnosticCollector(
        db_session,
        kind=DiagnosticRunKind.publish_job,
        account_id=account.id,
        job_id=None,
    )
    cb = collector.callback()
    cb("info", "start", "begin")
    cb("error", "upload", "failed")
    collector.finish("fail", "failed")

    run = db_session.get(DiagnosticRun, collector.run_id)
    assert run is not None
    assert run.kind == DiagnosticRunKind.publish_job
    assert len(load_run_lines(run)) == 2
    from app.db.models import Event

    assert db_session.query(Event).filter(Event.account_id == account.id).count() == 0


def test_collector_emits_event_on_login_fail(db_session):
    from app.db.models import Event, EventLevel

    account = _make_account(db_session, username="loginev")
    collector = DiagnosticCollector(
        db_session,
        kind=DiagnosticRunKind.first_login,
        account_id=account.id,
    )
    collector.error("login", "bad password")
    collector.finish("fail", "Неверный пароль")
    events = db_session.query(Event).filter(Event.account_id == account.id).all()
    assert len(events) == 1
    assert events[0].kind == "first_login"
    assert events[0].level == EventLevel.error
    assert events[0].message == "Неверный пароль"
