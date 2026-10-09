"""Autonomous POST /api/assistant/run: prompt in, Ollama tools including Playwright."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.assistant.chat import (
    BROWSER_TOOL_NAMES,
    RUN_PROMPT,
    TOOLS,
    run_tool,
    system_message,
    tool_specs,
)
from app.assistant.tools import ToolError
from app.browser.session_manager import BrowserSessionState, BrowserSessionStatus
from app.db.models import Account, GenerationJob, PipelineStatus, Platform, PostJob


@pytest.fixture()
def api_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)
    monkeypatch.setattr(settings, "worker_autostart", False, raising=True)

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "worker_autostart", False, raising=True)
    monkeypatch.setattr("app.proxies.pool.health_check", lambda *a, **kw: {"ip": "203.0.113.5"})

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def _call(name: str, arguments: dict) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"c-{name}",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def test_run_path_in_openapi(api_client):
    spec = api_client.get("/api/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/assistant/run" in paths
    assert "/api/assistant" in paths


def test_ui_tools_do_not_include_browser():
    names = {item["function"]["name"] for item in TOOLS}
    assert "start_browser" not in names
    assert "wait_render" in names
    assert "wait_plan" not in names
    run_names = {item["function"]["name"] for item in tool_specs(allow_browser=True)}
    assert "wait_render" in run_names
    assert BROWSER_TOOL_NAMES <= run_names
    assert "start_browser" in run_names
    assert "wait_plan" in run_names


def test_run_tool_allows_browser_status_during_login_orch(db_session, make_account, monkeypatch):
    from app.browser.session_manager import browser_session_manager

    account = make_account(username="orchstatus")
    browser_session_manager._sessions["orchstatus"] = BrowserSessionState(
        username="orchstatus",
        status=BrowserSessionStatus.running,
        login_orchestration=True,
    )
    monkeypatch.setattr(
        browser_session_manager,
        "status_dict",
        lambda username: {
            "username": username,
            "status": "running",
            "awaiting_code": False,
            "page_url": "https://www.instagram.com",
            "error": None,
            "vnc_path": "/vnc",
        },
    )
    out, _opened = run_tool(
        db_session,
        "browser_status",
        {"account_id": account.id},
        allow_browser=False,
    )
    assert out["username"] == "orchstatus"
    assert out["status"] == "running"


def test_run_tool_blocks_start_browser_even_during_login_orch(db_session, make_account):
    from app.browser.session_manager import browser_session_manager

    account = make_account(username="orchstart")
    browser_session_manager._sessions["orchstart"] = BrowserSessionState(
        username="orchstart",
        status=BrowserSessionStatus.running,
        login_orchestration=True,
    )
    try:
        run_tool(
            db_session,
            "start_browser",
            {"account_id": account.id},
            allow_browser=False,
        )
    except ToolError as exc:
        assert "assistant/run" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_ui_run_tool_refuses_start_browser(db_session):
    try:
        run_tool(db_session, "start_browser", {"username": "anyone"})
    except ToolError as exc:
        assert "assistant/run" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_run_endpoint_sends_prompt_with_browser_for_owner(auth_client, monkeypatch):
    from app.api.routes import assistant as route
    from app.assistant.chat import Answer

    seen: dict = {}

    def fake_ask(db, messages, **kwargs):
        seen["messages"] = messages
        seen["allow_browser"] = kwargs.get("allow_browser")
        return Answer(reply="ok", used=["start_browser"])

    monkeypatch.setattr(route, "ask", fake_ask)
    res = auth_client.post(
        "/api/assistant/run",
        json={"prompt": "войди и опубликуй"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 200
    assert seen["allow_browser"] is True
    assert seen["messages"][0]["content"] == "войди и опубликуй"


def _parse_stream_events(body: str) -> list[dict]:
    out: list[dict] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out


def test_stream_enables_browser_for_owner(auth_client, monkeypatch):
    from app.api.routes import assistant as route
    from app.assistant.chat import Answer

    seen: dict = {}

    def fake_stream(db, messages, **kwargs):
        seen["allow_browser"] = kwargs.get("allow_browser")
        yield Answer(reply="ok")

    monkeypatch.setattr(route, "stream", fake_stream)
    res = auth_client.post(
        "/api/assistant/stream",
        json={
            "messages": [{"role": "user", "content": "войди"}],
            "allow_browser": True,
        },
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 200
    assert seen["allow_browser"] is True
    events = _parse_stream_events(res.text)
    assert any(e.get("type") == "done" for e in events)


def test_stream_disables_browser_for_operator(auth_client, monkeypatch):
    from app.api.routes import assistant as route
    from app.assistant.chat import Answer

    created = auth_client.post(
        "/api/operators",
        headers={"Authorization": "Bearer secret-token"},
        json={"label": "stream-op"},
    ).json()
    op_password = created["password"]
    seen: dict = {}

    def fake_stream(db, messages, **kwargs):
        seen["allow_browser"] = kwargs.get("allow_browser")
        yield Answer(reply="ok")

    monkeypatch.setattr(route, "stream", fake_stream)
    res = auth_client.post(
        "/api/assistant/stream",
        json={
            "messages": [{"role": "user", "content": "войди"}],
            "allow_browser": True,
        },
        headers={"Authorization": f"Bearer {op_password}"},
    )
    assert res.status_code == 200
    assert seen["allow_browser"] is False


def test_run_endpoint_disables_browser_for_operator(auth_client, monkeypatch):
    from app.api.routes import assistant as route
    from app.assistant.chat import Answer

    created = auth_client.post(
        "/api/operators",
        headers={"Authorization": "Bearer secret-token"},
        json={"label": "run-op"},
    ).json()
    op_password = created["password"]
    seen: dict = {}

    def fake_ask(db, messages, **kwargs):
        seen["allow_browser"] = kwargs.get("allow_browser")
        return Answer(reply="ok", used=[])

    monkeypatch.setattr(route, "ask", fake_ask)
    res = auth_client.post(
        "/api/assistant/run",
        json={"prompt": "войди"},
        headers={"Authorization": f"Bearer {op_password}"},
    )
    assert res.status_code == 200
    assert seen["allow_browser"] is False


def test_system_message_run_overlay(tmp_path):
    message = system_message(tmp_path / "missing.md", allow_browser=True)
    assert RUN_PROMPT in message
    assert "start_browser" in message
    ui = system_message(tmp_path / "missing.md")
    assert RUN_PROMPT not in ui


def test_start_browser_youtube_does_not_need_session_id(db_session, make_account, monkeypatch):
    from app.assistant.tools import start_browser

    account = make_account(username="ytstudio", platform=Platform.youtube)

    async def fake_start(account, proxy, **kwargs):
        return SimpleNamespace(username=account.username)

    monkeypatch.setattr(
        "app.browser.session_manager.browser_session_manager.start_session",
        fake_start,
    )
    monkeypatch.setattr(
        "app.browser.session_manager.browser_session_manager.status_dict",
        lambda username: {
            "username": username,
            "status": "running",
            "awaiting_code": False,
            "page_url": "https://studio.youtube.com",
            "error": None,
            "vnc_path": "/api/accounts/ytstudio/browser/vnc/ws",
        },
    )
    out = start_browser(db_session, account_id=account.id)
    assert out["username"] == "ytstudio"
    assert out["platform"] == "youtube"
    assert out["status"] == "running"


def test_create_render_without_key_quotes_healthcheck(db_session, monkeypatch):
    from app.assistant.tools import create_render
    from app.config import settings

    monkeypatch.setattr(settings, "fal_api_key", "")
    monkeypatch.setattr(settings, "hf_token", "")
    monkeypatch.setattr(settings, "pollinations_video_url", "")
    monkeypatch.setattr(settings, "wan_base_url", "")
    monkeypatch.setattr(settings, "hf_space_id", "")
    try:
        create_render(db_session, prompt="туман")
    except ToolError as exc:
        assert "не настроен" in str(exc)
        assert "API-ключ" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_wait_render_returns_when_done(db_session, make_account):
    from app.assistant.tools import wait_render

    account = make_account()
    job = GenerationJob(
        prompt="fog",
        backend="fal",
        status=PipelineStatus.done,
        account_id=account.id,
    )
    db_session.add(job)
    db_session.commit()
    out = wait_render(db_session, job.id, timeout_s=0.2, poll_s=0.05)
    assert out["status"] == "done"


def test_wait_plan_returns_when_done(db_session, make_account):
    from app.assistant.tools import wait_plan
    from app.db.models import PlanJob

    account = make_account()
    job = PlanJob(
        account_id=account.id,
        count=1,
        status=PipelineStatus.done,
        planned=1,
    )
    db_session.add(job)
    db_session.commit()
    out = wait_plan(db_session, job.id, timeout_s=0.2, poll_s=0.05)
    assert out["status"] == "done"
    assert out["generation_ids"] == []


def test_ui_run_tool_refuses_wait_plan(db_session):
    try:
        run_tool(db_session, "wait_plan", {"plan_id": 1})
    except ToolError as exc:
        assert "assistant/run" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_run_chain_proxy_account_browser_render_publish(
    db_session, monkeypatch, app_env
):
    from pathlib import Path

    from app.assistant import chat
    from app.config import Settings, settings

    monkeypatch.setattr(chat, "_prepare_runtime", lambda settings: None)
    monkeypatch.setattr(settings, "fal_api_key", "k")

    clip = Path(app_env.video_source_dir) / "clip.mp4"
    clip.write_bytes(b"fake")

    async def fake_start(account, proxy, **kwargs):
        return SimpleNamespace(username=account.username)

    monkeypatch.setattr(
        "app.browser.session_manager.browser_session_manager.start_session",
        fake_start,
    )
    monkeypatch.setattr(
        "app.browser.session_manager.browser_session_manager.status_dict",
        lambda username: {
            "username": username,
            "status": "running",
            "awaiting_code": False,
            "page_url": None,
            "error": None,
            "vnc_path": None,
        },
    )

    def fake_wait(db, job_id, **kwargs):
        job = db.get(GenerationJob, job_id)
        job.status = PipelineStatus.done
        db.commit()
        return {"id": job.id, "status": "done"}

    monkeypatch.setattr("app.assistant.tools.wait_render", fake_wait)

    def fake_conn(account, db, probe_mobile=False):
        return SimpleNamespace(
            username=account.username,
            overall_ok=True,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=True, error=None),
            instagram_auth=SimpleNamespace(ok=True, error=None),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_conn)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(chat, "http_client", lambda *a, **k: FakeClient())

    n = {"i": 0}

    def fake_complete(client, settings, thread, said, **_kwargs):
        if False:
            yield chat.Step(kind="token", text="")
        n["i"] += 1
        if n["i"] == 1:
            return _call("create_proxy", {"label": "px", "url": "http://u:p@127.0.0.1:8080"})
        if n["i"] == 2:
            return _call(
                "create_account",
                {
                    "username": "ytuser",
                    "password": "secret",
                    "proxy_label": "px",
                    "platform": "youtube",
                },
            )
        if n["i"] == 3:
            account = db_session.scalar(select(Account).where(Account.username == "ytuser"))
            return _call("start_browser", {"account_id": account.id})
        if n["i"] == 4:
            return _call("create_render", {"prompt": "fog over a forest"})
        if n["i"] == 5:
            account = db_session.scalar(select(Account).where(Account.username == "ytuser"))
            return _call("publish_now", {"account_id": account.id, "filename": "clip.mp4"})
        return {"role": "assistant", "content": "готово"}

    monkeypatch.setattr(chat, "_complete", fake_complete)
    cfg = Settings(_env_file=None)
    answer = chat.ask(
        db_session,
        [{"role": "user", "content": "прокси, аккаунт, вход, рендер, публикация"}],
        settings=cfg,
        allow_browser=True,
    )
    assert answer.used == [
        "create_proxy",
        "create_account",
        "start_browser",
        "create_render",
        "wait_render",
        "publish_now",
    ]
    account = db_session.scalar(select(Account).where(Account.username == "ytuser"))
    assert account is not None
    assert account.platform is Platform.youtube
    jobs = list(db_session.scalars(select(PostJob)).all())
    assert len(jobs) == 1
    assert answer.reply == "готово"
