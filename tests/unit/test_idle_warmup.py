"""Tests for app.behavior.idle_warmup.

idle_warmup is a publish-less warmup pass: it logs in, runs ``warmup``, then
stamps ``Account.last_idle_warmup_at``. We mock the heavyweight pieces and
assert the side-effects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.behavior import idle_warmup as idle_module
from app.db import Account, AccountStatus, Event


@pytest.fixture()
def fake_login(monkeypatch):
    """Replace login_or_resume with a stub returning a sentinel client."""
    captured = {}

    class _Client:
        pass

    def _factory(**kwargs):
        captured.update(kwargs)
        return _Client()

    monkeypatch.setattr(idle_module, "login_or_resume", _factory)
    return captured


def test_idle_warmup_skips_paused_account(app_env, db_session, make_account, fake_login):
    account = make_account(status=AccountStatus.paused)
    assert idle_module.idle_warmup(account.username) is False


def test_idle_warmup_skips_account_without_proxy(app_env, db_session, make_account, fake_login):
    account = make_account()
    account.proxy_id = None
    db_session.commit()
    assert idle_module.idle_warmup(account.username) is False


def test_idle_warmup_happy_path_stamps_account(
    app_env, db_session, make_account, fake_login, monkeypatch
):
    account = make_account()
    monkeypatch.setattr(idle_module, "health_check_cached", lambda url, **kwargs: None)
    monkeypatch.setattr(
        idle_module, "ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: object(),
    )
    monkeypatch.setattr(idle_module, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(idle_module, "think", lambda *a, **k: 0.0)

    assert idle_module.idle_warmup(account.username) is True

    db_session.expire_all()
    refreshed = db_session.get(Account, account.id)
    assert refreshed.last_idle_warmup_at is not None

    events = db_session.query(Event).filter(Event.kind == "idle_warmup").all()
    assert events


def test_idle_warmup_proxy_unhealthy(app_env, db_session, make_account, fake_login, monkeypatch):
    account = make_account()
    from app.proxies.pool import ProxyError

    def _bad(url, **_):
        raise ProxyError("down")

    monkeypatch.setattr(idle_module, "health_check_cached", _bad)
    assert idle_module.idle_warmup(account.username) is False


def test_pick_idle_account_excludes_recently_warmed(app_env, db_session, make_account):
    """Account warmed in the last MIN_IDLE_HOURS hours must not be chosen."""
    fresh = make_account(username="fresh")
    fresh.last_idle_warmup_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()
    candidate = idle_module._pick_idle_account(db_session)
    assert candidate is None or candidate.username != "fresh"


def test_pick_idle_account_returns_old_or_unstamped(app_env, db_session, make_account):
    stale = make_account(username="stale")
    stale.last_idle_warmup_at = datetime.now(timezone.utc) - timedelta(hours=24)
    db_session.commit()
    candidate = idle_module._pick_idle_account(db_session)
    assert candidate is not None
    assert candidate.username == "stale"


def test_pick_idle_account_skips_cooldown(app_env, db_session, make_account):
    on_cooldown = make_account(username="cd")
    on_cooldown.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=12)
    on_cooldown.last_idle_warmup_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()
    candidate = idle_module._pick_idle_account(db_session)
    assert candidate is None or candidate.username != "cd"


def test_maybe_run_idle_warmup_respects_probability(monkeypatch):
    """When the dice roll exceeds the threshold, the function returns False
    without touching the DB."""
    import random as _random

    monkeypatch.setattr(_random, "random", lambda: 1.0)
    assert idle_module.maybe_run_idle_warmup(probability=0.05) is False
