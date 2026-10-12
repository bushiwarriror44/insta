"""Agent login autonomy: codes, ensure session, browser gate, gaps plan."""
import pytest

from app.api.schemas import FirstLoginOut
from app.assistant import tools
from app.assistant.chat import run_tool
from app.assistant.tools import ToolError
from app.browser.session_manager import BrowserSessionState, BrowserSessionStatus


def test_submit_login_code_writes_challenge_file(db_session, make_account, tmp_path, monkeypatch):
    from app.accounts import challenge as ch

    monkeypatch.setattr(ch, "CHALLENGES_DIR", tmp_path)
    account = make_account(username="codeuser")
    out = tools.submit_login_code(db_session, code="123456", account_id=account.id)
    assert out["method"] == "challenge_file"
    assert (tmp_path / "codeuser.code").read_text(encoding="utf-8") == "123456"


def test_login_orchestration_allows_browser_status(db_session, make_account, monkeypatch):
    from app.browser.session_manager import browser_session_manager

    account = make_account(username="orchuser")
    browser_session_manager._sessions["orchuser"] = BrowserSessionState(
        username="orchuser",
        status=BrowserSessionStatus.awaiting_code,
        login_orchestration=True,
        awaiting_code=True,
    )
    assert tools.login_orchestration_allows_browser_tool(
        db_session, "browser_status", account_id=account.id
    )


def test_run_tool_blocks_submit_browser_code_without_orch(db_session, make_account):
    account = make_account(username="gateuser")
    with pytest.raises(ToolError, match="только в POST"):
        run_tool(
            db_session,
            "submit_browser_code",
            {"account_id": account.id, "code": "123456"},
        )


def test_run_tool_allows_submit_browser_code_with_orch(db_session, make_account, monkeypatch):
    from app.browser.session_manager import browser_session_manager

    account = make_account(username="gateok")
    browser_session_manager._sessions["gateok"] = BrowserSessionState(
        username="gateok",
        status=BrowserSessionStatus.awaiting_code,
        login_orchestration=True,
        awaiting_code=True,
    )

    monkeypatch.setattr(
        tools,
        "submit_browser_code",
        lambda db, **kw: {"username": "gateok", "ok": True, "status": "running"},
    )
    out, _opened = run_tool(
        db_session,
        "submit_browser_code",
        {"account_id": account.id, "code": "654321"},
    )
    assert out["ok"] is True


def test_get_session_soft_not_ready_instagram(db_session, make_account):
    account = make_account(username="nosess")
    out = tools.get_session(db_session, account.id)
    assert out["ready"] is False
    assert out["platform"] == "instagram"
    assert "hint" in out


def test_get_session_soft_not_ready_youtube(db_session, make_account):
    account = make_account(username="nostudio", platform="youtube")
    out = tools.get_session(db_session, account.id)
    assert out["ready"] is False
    assert out["platform"] == "youtube"


def test_account_details_includes_session_source(db_session, make_account):
    account = make_account(username="srcuser")
    out = tools.account_details(db_session, account.id)
    assert out["session_source"] in ("database", "session_file", "playwright", "none")


def test_ig_challenge_payload_no_browser_actions(db_session, make_account):
    account = make_account(username="igch")
    out = FirstLoginOut(
        run_id=1,
        ok=False,
        challenge=True,
        browser_tab_hint=False,
        error="нужен challenge",
        logs=[],
    )
    payload = tools._login_result_payload(account, out)
    assert payload["browser_tab_hint"] is False
    assert payload["browser_session_active"] is False
    assert payload["next_actions"] == ["submit_login_code", "login_account"]
    assert payload.get("ask") is True
    assert payload["fields"][0]["id"] == "verification_code"


def test_ensure_account_session_blocked_when_vnc_in_progress(db_session, make_account, make_proxy):
    from app.browser.session_manager import browser_session_manager

    proxy = make_proxy(label="px-busy-ens")
    account = make_account(username="busyens", proxy=proxy)
    browser_session_manager._sessions["busyens"] = BrowserSessionState(
        username="busyens",
        status=BrowserSessionStatus.awaiting_code,
        login_orchestration=True,
        awaiting_code=True,
    )
    out = tools.ensure_account_session(db_session, account.id)
    assert out.get("login_in_progress") is True
    assert out.get("ensure_account_session") is True
    assert out["ok"] is False


def test_login_account_blocked_when_vnc_in_progress(db_session, make_account):
    from app.browser.session_manager import browser_session_manager

    account = make_account(username="busyuser")
    browser_session_manager._sessions["busyuser"] = BrowserSessionState(
        username="busyuser",
        status=BrowserSessionStatus.awaiting_code,
        login_orchestration=True,
        awaiting_code=True,
    )
    out = tools.login_account(db_session, account.id)
    assert out.get("login_in_progress") is True
    assert out["ok"] is False


def test_login_account_continues_with_verification_code_when_busy(db_session, make_account, monkeypatch):
    from app.browser.session_manager import browser_session_manager

    account = make_account(username="busy2")
    browser_session_manager._sessions["busy2"] = BrowserSessionState(
        username="busy2",
        status=BrowserSessionStatus.awaiting_code,
        login_orchestration=True,
        awaiting_code=True,
    )
    monkeypatch.setattr(
        "app.accounts.login_orchestrator.run_autonomous_account_login",
        lambda *a, **k: FirstLoginOut(run_id=2, ok=True, logs=[]),
    )
    monkeypatch.setattr(
        tools,
        "submit_login_code",
        lambda *a, **k: {"ok": True, "method": "browser"},
    )
    out = tools.login_account(db_session, account.id, verification_code="111222")
    assert out["ok"] is True


def test_ensure_account_session_skips_when_ready(db_session, make_account, make_proxy, monkeypatch):
    proxy = make_proxy(label="px-ens")
    account = make_account(username="readyig", proxy=proxy)

    monkeypatch.setattr(
        tools,
        "get_session",
        lambda db, aid, **kw: {"ready": True, "platform": "instagram"},
    )
    monkeypatch.setattr(
        tools,
        "test_connection",
        lambda db, aid, **kw: {"ok": True},
    )
    out = tools.ensure_account_session(db_session, account.id)
    assert out["ok"] is True
    assert out["skipped_login"] is True


def test_ensure_account_session_runs_login(db_session, make_account, make_proxy, monkeypatch):
    proxy = make_proxy(label="px-ens2")
    account = make_account(username="needig", proxy=proxy)

    monkeypatch.setattr(tools, "get_session", lambda db, aid, **kw: {"ready": False})
    monkeypatch.setattr(
        tools,
        "login_account",
        lambda db, aid, **kw: {
            "ok": True,
            "run_id": 9,
            "account_logs_hint": "x",
        },
    )
    monkeypatch.setattr(
        tools,
        "test_connection",
        lambda db, aid, **kw: {"ok": True},
    )
    out = tools.ensure_account_session(db_session, account.id)
    assert out["ok"] is True
    assert out["skipped_login"] is False


def test_ensure_account_session_ready_uses_test_connection_ok(
    db_session, make_account, make_proxy, monkeypatch
):
    from datetime import datetime, timezone

    from app.accounts.session_manager import ProbeSessionResult
    from app.proxies.pool import HealthSnapshot

    proxy = make_proxy(label="px-real-conn")
    account = make_account(username="realconn", proxy=proxy, session_id="a" * 40)
    snapshot = HealthSnapshot(
        ok=True,
        ip="1.2.3.4",
        country="US",
        instagram_reachable=True,
        instagram_login_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        tools,
        "get_session",
        lambda db, aid, **kw: {"ready": True, "platform": "instagram"},
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.health_check_record",
        lambda db, px: (True, snapshot, None),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.ensure_fingerprint_and_proxy",
        lambda username, country="US", **kwargs: object(),
    )
    monkeypatch.setattr(
        "app.accounts.connection_test.probe_session_auth",
        lambda **kwargs: ProbeSessionResult(ok=True, method="sessionid", ig_username="realconn"),
    )
    out = tools.ensure_account_session(db_session, account.id)
    assert out["ok"] is True
    assert out["skipped_login"] is True
    assert out["connection_test"]["ok"] is True


def test_stream_ask_step_from_login_challenge_payload():
    """Mirror chat.stream tool-result handling for challenge ask."""
    result = {
        "ask": True,
        "why": "Нужен код",
        "questions": [],
        "fields": [{"id": "verification_code", "label": "Код", "kind": "password"}],
    }
    assert result.get("ask")
    fields = list(result.get("fields") or [])
    assert fields[0]["id"] == "verification_code"
