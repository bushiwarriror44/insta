"""Login tool status hook for assistant stream."""
from app.assistant import tools


def test_login_status_hook_delivers_messages():
    seen: list[tuple[str, str | None]] = []
    tools.set_login_status_hook(lambda title, detail=None: seen.append((title, detail)))
    try:
        tools._emit_login_status("Автовход", "@alice")
    finally:
        tools.clear_login_status_hook()
    assert seen == [("Автовход", "@alice")]
    tools._emit_login_status("ignored")
    assert len(seen) == 1


def test_login_instagram_returns_run_id(db_session, make_account, make_proxy, monkeypatch):
    from app.api.schemas import FirstLoginOut

    proxy = make_proxy(label="px-li")
    account = make_account(username="loguser", proxy=proxy)

    def _fake_run(acc, db, *, surface=None, on_status=None):
        if on_status:
            on_status("Тест", "шаг")
        return FirstLoginOut(
            run_id=42,
            ok=True,
            error=None,
            challenge=False,
            session_imported=True,
            logs=[],
        )

    monkeypatch.setattr(
        "app.accounts.login_orchestrator.run_autonomous_instagram_login",
        _fake_run,
    )
    out = tools.login_instagram(db_session, account.id)
    assert out["ok"] is True
    assert out["run_id"] == 42
    assert "account_logs" in out["account_logs_hint"]


def test_login_account_routes_studio(db_session, make_account, make_proxy, monkeypatch):
    from app.api.schemas import FirstLoginOut
    from app.db.models import Platform

    proxy = make_proxy(label="px-yt-la")
    account = make_account(username="ytla", proxy=proxy, platform=Platform.youtube)

    def _fake_studio(acc, db, *, on_status=None):
        return FirstLoginOut(run_id=77, ok=True, session_imported=True, logs=[])

    monkeypatch.setattr(
        "app.accounts.studio_login_service.run_studio_login",
        _fake_studio,
    )
    out = tools.login_account(db_session, account.id)
    assert out["ok"] is True
    assert out["run_id"] == 77
    assert "studio_login" in out["account_logs_hint"]
