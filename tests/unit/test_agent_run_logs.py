"""Run journal and the needs-a-person pause."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import AuthPrincipal
from app.assistant.chat import Answer
from app.assistant.run_log import bind, log_tool
from app.db.models import AgentRunLog, AssistantJob


def _client(app_env, holder: dict):
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


def test_tool_line_hides_secrets(app_env):
    db = app_env.SessionLocal()
    job = AssistantJob(actor="owner", prompt="войти", status="running")
    db.add(job)
    db.commit()
    db.refresh(job)
    with bind(job.id):
        log_tool(
            "вхожу в аккаунт",
            {"username": "ada", "password": "secret-pass", "proxy_url": "socks5://user:pw@10.0.0.1:1080"},
            {"ok": True},
        )
    db.expire_all()
    line = db.scalars(select(AgentRunLog)).one()
    assert "ada" in line.text
    assert "secret-pass" not in line.text
    assert "socks5://" not in line.text
    assert "***" in line.text
    db.close()


def test_ask_waits_for_the_operator(app_env, monkeypatch):
    from tests.unit.test_assistant_jobs import _wait_done

    monkeypatch.setattr("app.assistant.reports.notify_telegram", lambda *_a, **_k: None)
    monkeypatch.setattr("app.assistant.reports.evidence_url", lambda *_a, **_k: None)

    def fake_stream(*_args, **_kwargs):
        log_tool("смотрю аккаунты", {"username": "ada"}, {"ask": True})
        yield Answer(reply="Нужен код входа", asks=["Какой код?"])

    monkeypatch.setattr("app.assistant.chat.stream", fake_stream)
    holder = {"principal": AuthPrincipal(role="owner")}
    client = _client(app_env, holder)
    created = client.post(
        "/api/assistant/jobs",
        json={"messages": [{"role": "user", "content": "войти"}], "client_chat_id": "chat-1"},
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["id"]
    row = _wait_done(app_env.SessionLocal, job_id)
    assert row.status == "needs_user"
    assert "Нужен код входа" in (row.reply or "")

    logs = client.get("/api/agent-reports/logs")
    assert logs.status_code == 200, logs.text
    body = logs.json()
    assert body[0]["job_id"] == job_id
    assert "secret" not in body[0]["text"]
    assert "смотрю аккаунты" in body[0]["text"]

    holder["principal"] = AuthPrincipal(role="operator", operator_id=4)
    assert client.get("/api/agent-reports/logs").json() == []
    assert client.get("/api/assistant/jobs/active").json() is None
    assert client.post(f"/api/assistant/jobs/{job_id}/ack").status_code == 404

    holder["principal"] = AuthPrincipal(role="owner")
    active = client.get("/api/assistant/jobs/active")
    assert active.json()["status"] == "needs_user"
    closed = client.post(f"/api/assistant/jobs/{job_id}/ack")
    assert closed.status_code == 200
    assert closed.json()["status"] == "done"
    assert client.get("/api/assistant/jobs/active").json() is None
