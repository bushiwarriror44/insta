"""Tests for app.alerts.telegram."""
from __future__ import annotations

import json

import httpx
import respx
from sqlalchemy import select

from app.alerts import telegram as tg
from app.config import settings
from app.db import Event, EventLevel


def test_send_disabled_when_no_token(app_env, db_session, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")

    tg.send("hi", level=EventLevel.warn, kind="x")

    rows = db_session.scalars(select(Event).where(Event.kind == "x")).all()
    assert len(rows) == 1
    assert rows[0].level == EventLevel.warn


@respx.mock
def test_send_posts_to_telegram(app_env, db_session, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "BOTTOK")
    monkeypatch.setattr(settings, "telegram_chat_id", "CHATID")

    route = respx.post("https://api.telegram.org/botBOTTOK/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    tg.send("hi there", level=EventLevel.info, kind="alert")
    assert route.called
    call = route.calls[0]
    payload = json.loads(call.request.read().decode("utf-8"))
    assert payload["chat_id"] == "CHATID"
    assert "hi there" in payload["text"]
    assert "ИНФО" in payload["text"]

    rows = db_session.scalars(select(Event).where(Event.kind == "alert")).all()
    assert len(rows) == 1


@respx.mock
def test_send_swallows_http_errors(app_env, db_session, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "BOTTOK")
    monkeypatch.setattr(settings, "telegram_chat_id", "CHATID")
    respx.post("https://api.telegram.org/botBOTTOK/sendMessage").mock(
        return_value=httpx.Response(500, text="boom")
    )

    tg.send("nope", level=EventLevel.error, kind="kk")

    rows = db_session.scalars(select(Event).where(Event.kind == "kk")).all()
    assert len(rows) == 1


@respx.mock
def test_send_swallows_network_exception(app_env, db_session, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "BOTTOK")
    monkeypatch.setattr(settings, "telegram_chat_id", "CHATID")
    respx.post("https://api.telegram.org/botBOTTOK/sendMessage").mock(
        side_effect=httpx.ConnectError("conn refused")
    )

    tg.send("network down", level=EventLevel.error, kind="netfail")

    rows = db_session.scalars(select(Event).where(Event.kind == "netfail")).all()
    assert len(rows) == 1


def test_notify_helpers_record_proper_kinds(app_env, db_session, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")

    tg.notify_challenge("alice", "EMAIL", account_id=None)
    tg.notify_blocked("alice", account_id=None, reason="bad")
    tg.notify_proxy_down("res-1", error="dead")
    tg.notify_publish_failure("alice", account_id=None, error="x", attempt=1)

    kinds = {row.kind for row in db_session.scalars(select(Event)).all()}
    assert {"challenge", "blocked", "proxy_down", "publish_failed"} <= kinds


def test_event_persist_failure_does_not_crash(app_env, monkeypatch):
    """If the DB raises, send must not propagate."""
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")

    class BadSession:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def add(self, _row):
            raise RuntimeError("db down")

        def commit(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(tg, "SessionLocal", lambda: BadSession())
    tg.send("ok", level=EventLevel.info, kind="z")
