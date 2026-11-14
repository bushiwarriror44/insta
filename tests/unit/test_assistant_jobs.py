"""Pause, stop, and per-user isolation for background assistant runs."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import AuthPrincipal
from app.assistant.chat import Answer
from app.assistant.job_control import RESTART_TEXT, STOPPED_TEXT
from app.db.models import AgentReport, AssistantJob


def _hold_stream(
    gate: threading.Event,
    release: threading.Event,
    second: threading.Event,
    arrived: threading.Event | None = None,
):
    def fake_stream(*_args, control=None, **_kwargs):
        if control is not None:
            control()
        gate.set()
        assert release.wait(3)
        if arrived is not None:
            arrived.set()
        if control is not None:
            control()
        second.set()
        yield Answer(reply="готово")

    return fake_stream


@pytest.fixture()
def quiet_reports(monkeypatch):
    monkeypatch.setattr("app.assistant.reports.notify_telegram", lambda *_a, **_k: None)
    monkeypatch.setattr("app.assistant.reports.evidence_url", lambda *_a, **_k: None)


def _wait_thread(job_id: int) -> None:
    name = f"assistant-job-{job_id}"
    deadline = time.time() + 3
    while time.time() < deadline:
        match = [item for item in threading.enumerate() if item.name == name]
        if not match:
            return
        match[0].join(0.1)
        if not match[0].is_alive():
            return
    raise AssertionError(name)


def _wait_done(session_factory, job_id: int) -> AssistantJob:
    deadline = time.time() + 3
    db = session_factory()
    try:
        row = None
        while time.time() < deadline:
            db.expire_all()
            row = db.get(AssistantJob, job_id)
            if row is not None and row.status not in ("running", "paused"):
                return row
            time.sleep(0.05)
        raise AssertionError(f"job {job_id} still {getattr(row, 'status', None)}")
    finally:
        db.close()


def test_pause_blocks_the_next_step(app_env, monkeypatch, quiet_reports):
    from app.assistant import job_control

    gate = threading.Event()
    release = threading.Event()
    second = threading.Event()
    arrived = threading.Event()
    monkeypatch.setattr("app.assistant.chat.stream", _hold_stream(gate, release, second, arrived))
    db = app_env.SessionLocal()
    row, fresh = job_control.start_job(
        db, "owner", [{"role": "user", "content": "Покажи аккаунты"}]
    )
    assert fresh
    assert gate.wait(2)
    assert job_control.set_status(db, row.id, "owner", "paused").status == "paused"
    release.set()
    assert arrived.wait(2)
    assert not second.wait(0.35)
    assert job_control.set_status(db, row.id, "owner", "running").status == "running"
    assert second.wait(2)
    assert _wait_done(app_env.SessionLocal, row.id).status == "done"
    db.close()


def test_stop_ends_the_run(app_env, monkeypatch, quiet_reports):
    from app.assistant import job_control

    gate = threading.Event()
    release = threading.Event()
    second = threading.Event()
    monkeypatch.setattr("app.assistant.chat.stream", _hold_stream(gate, release, second))
    db = app_env.SessionLocal()
    row, _fresh = job_control.start_job(db, "owner", [{"role": "user", "content": "стой"}])
    assert gate.wait(2)
    assert job_control.set_status(db, row.id, "owner", "stopped").error == STOPPED_TEXT
    release.set()
    _wait_thread(row.id)
    db.expire_all()
    saved = db.get(AssistantJob, row.id)
    assert not second.is_set()
    assert saved.status == "stopped"
    report = db.scalars(select(AgentReport)).one()
    assert report.error == STOPPED_TEXT
    assert "выполнение остановлено" in report.reply
    db.close()


def test_restart_fails_only_orphaned_runs(app_env):
    from app.assistant import job_control

    db = app_env.SessionLocal()
    orphan = AssistantJob(actor="owner", prompt="старый", status="running")
    live = AssistantJob(actor="owner", prompt="живой", status="paused")
    db.add_all([orphan, live])
    db.commit()
    with job_control._lock:
        job_control._threads.add(live.id)
    try:
        assert job_control.fail_interrupted(db) == 1
        db.expire_all()
        assert db.get(AssistantJob, orphan.id).status == "failed"
        assert db.get(AssistantJob, orphan.id).error == RESTART_TEXT
        assert db.get(AssistantJob, live.id).status == "paused"
    finally:
        with job_control._lock:
            job_control._threads.discard(live.id)
        db.close()


def _client(app_env, monkeypatch, holder: dict):
    from app.api import deps as api_deps
    from app.api.main import create_app

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    app.dependency_overrides[api_deps.require_token] = lambda: holder["principal"]
    return TestClient(app)


def test_owner_and_operator_do_not_share_jobs(app_env, monkeypatch, quiet_reports):
    gate = threading.Event()
    release = threading.Event()
    second = threading.Event()
    monkeypatch.setattr("app.assistant.chat.stream", _hold_stream(gate, release, second))
    holder = {"principal": AuthPrincipal(role="owner")}
    client = _client(app_env, monkeypatch, holder)
    created = client.post(
        "/api/assistant/jobs",
        json={"messages": [{"role": "user", "content": "свои"}], "client_chat_id": "chat-owner"},
    )
    assert created.status_code == 200, created.text
    owner_id = created.json()["id"]
    assert gate.wait(2)
    assert client.get("/api/assistant/jobs/active").json()["id"] == owner_id

    holder["principal"] = AuthPrincipal(role="operator", operator_id=4)
    assert client.get("/api/assistant/jobs/active").json() is None
    assert client.get(f"/api/assistant/jobs/{owner_id}").status_code == 404
    assert client.post(f"/api/assistant/jobs/{owner_id}/stop").status_code == 404
    other = client.post(
        "/api/assistant/jobs",
        json={"messages": [{"role": "user", "content": "чужие"}], "client_chat_id": "chat-op"},
    )
    assert other.status_code == 200, other.text
    operator_id = other.json()["id"]
    assert operator_id != owner_id
    assert client.get("/api/assistant/jobs/active").json()["actor"] == "operator:4"

    holder["principal"] = AuthPrincipal(role="owner")
    again = TestClient(client.app).get("/api/assistant/jobs/active")
    assert again.status_code == 200
    assert again.json()["id"] == owner_id
    assert again.json()["status"] == "running"
    assert client.get(f"/api/assistant/jobs/{operator_id}").status_code == 404
    duplicate = client.post(
        "/api/assistant/jobs",
        json={"messages": [{"role": "user", "content": "ещё"}]},
    )
    assert duplicate.status_code == 409

    release.set()
    assert _wait_done(app_env.SessionLocal, owner_id).status == "done"
    assert _wait_done(app_env.SessionLocal, operator_id).status == "done"


def test_active_stays_running_for_a_new_client(app_env, monkeypatch, quiet_reports):
    gate = threading.Event()
    release = threading.Event()
    second = threading.Event()
    monkeypatch.setattr("app.assistant.chat.stream", _hold_stream(gate, release, second))
    holder = {"principal": AuthPrincipal(role="owner")}
    first = _client(app_env, monkeypatch, holder)
    created = first.post(
        "/api/assistant/jobs",
        json={"messages": [{"role": "user", "content": "Покажи аккаунты"}], "client_chat_id": "chat-1"},
    )
    assert created.status_code == 200
    assert gate.wait(2)
    second_client = TestClient(first.app)
    active = second_client.get("/api/assistant/jobs/active")
    assert active.json()["status"] == "running"
    assert active.json()["client_chat_id"] == "chat-1"
    release.set()
    assert _wait_done(app_env.SessionLocal, created.json()["id"]).status == "done"
