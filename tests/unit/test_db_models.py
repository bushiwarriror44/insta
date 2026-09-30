"""Tests for SQLAlchemy models, init_db and integrity constraints."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db import (
    Account,
    AccountStatus,
    DailyStat,
    Device,
    Event,
    EventLevel,
    PostJob,
    PostJobStatus,
    PostLog,
    Proxy,
)


def test_init_db_creates_all_tables(app_env):
    inspector = inspect(app_env.engine)
    tables = set(inspector.get_table_names())
    expected = {
        "accounts",
        "proxies",
        "devices",
        "post_jobs",
        "post_logs",
        "daily_stats",
        "events",
        "diagnostic_runs",
        "panel_operators",
        "panel_settings",
        "media_assets",
        "plan_jobs",
        "generation_jobs",
        "agent_runs",
        "clarifications",
        "prompt_presets",
        "channel_sources",
        "compositions",
        "composition_clips",
        "worker_beats",
    }
    assert expected.issubset(tables), f"missing tables: {expected - tables}"


def test_init_db_adds_pending_email_totp_columns(app_env):
    """Old DBs missing email/2FA columns must pick them up via auto-init."""
    from sqlalchemy import text

    from app.db.session import init_db

    engine = app_env.engine
    with engine.begin() as conn:
        for column in ("email", "email_password", "totp_seed"):
            conn.execute(text(f"ALTER TABLE accounts DROP COLUMN {column}"))

    cols_before = {c["name"] for c in inspect(engine).get_columns("accounts")}
    assert "email" not in cols_before
    assert "email_password" not in cols_before
    assert "totp_seed" not in cols_before

    init_db()

    cols = {c["name"] for c in inspect(engine).get_columns("accounts")}
    assert "email" in cols
    assert "email_password" in cols
    assert "totp_seed" in cols


def test_init_db_adds_pending_generation_multimodal_columns(app_env):
    """Old DBs missing multimodal columns must pick them up via auto-init."""
    from sqlalchemy import text

    from app.db.session import init_db

    engine = app_env.engine
    with engine.begin() as conn:
        for column in ("input_mode", "reference_json"):
            conn.execute(text(f"ALTER TABLE generation_jobs DROP COLUMN {column}"))

    cols_before = {c["name"] for c in inspect(engine).get_columns("generation_jobs")}
    assert "input_mode" not in cols_before
    assert "reference_json" not in cols_before

    init_db()

    cols = {c["name"] for c in inspect(engine).get_columns("generation_jobs")}
    assert "input_mode" in cols
    assert "reference_json" in cols


def test_account_username_unique(db_session, make_proxy):
    proxy = make_proxy()
    db_session.add(Account(username="dup", password="x", proxy_id=proxy.id))
    db_session.commit()
    db_session.add(Account(username="dup", password="y", proxy_id=proxy.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_proxy_label_unique(db_session):
    db_session.add(Proxy(label="lbl", url="http://h:1"))
    db_session.commit()
    db_session.add(Proxy(label="lbl", url="http://h:2"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_daily_stat_uniqueness(db_session, make_account):
    account = make_account()
    db_session.add(DailyStat(account_id=account.id, date_key="2026-01-01", posts_count=1))
    db_session.commit()
    db_session.add(DailyStat(account_id=account.id, date_key="2026-01-01", posts_count=2))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_account_cascade_delete_clears_children(db_session, make_account):
    account = make_account()
    device = Device(
        account_id=account.id,
        settings_json="{}",
        user_agent="UA",
        locale="en_US",
        country="US",
        country_code=1,
        timezone_offset=-25200,
    )
    job = PostJob(
        account_id=account.id,
        source_video_path="x.mp4",
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.queued,
    )
    db_session.add_all([device, job])
    db_session.commit()
    db_session.flush()

    db_session.add(PostLog(job_id=job.id, account_id=account.id, success=True))
    db_session.add(DailyStat(account_id=account.id, date_key="2026-01-02"))
    db_session.commit()

    db_session.delete(account)
    db_session.commit()

    assert db_session.scalar(select(Device).where(Device.account_id == account.id)) is None
    assert db_session.scalar(select(PostJob).where(PostJob.account_id == account.id)) is None
    assert db_session.scalar(select(PostLog).where(PostLog.account_id == account.id)) is None
    assert db_session.scalar(select(DailyStat).where(DailyStat.account_id == account.id)) is None


def test_account_status_default(db_session, make_proxy):
    proxy = make_proxy()
    account = Account(username="x", password="p", proxy_id=proxy.id)
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    assert account.status == AccountStatus.active


def test_event_level_enum_persists(db_session):
    db_session.add(Event(level=EventLevel.warn, kind="x", message="hi"))
    db_session.commit()
    row = db_session.scalar(select(Event).where(Event.kind == "x"))
    assert row is not None
    assert row.level == EventLevel.warn
