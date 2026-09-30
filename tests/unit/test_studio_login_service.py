"""Studio login orchestration service."""
from app.accounts.studio_login_service import run_studio_login
from app.api.schemas import FirstLoginOut


def test_studio_login_no_proxy(db_session, make_account, monkeypatch):
    monkeypatch.setattr(
        "app.accounts.studio_login_service.playwright_browsers_available",
        lambda: True,
    )
    account = make_account(username="yt1", platform="youtube")
    account.proxy_id = None
    db_session.commit()
    out = run_studio_login(account, db_session)
    assert out.ok is False
    assert out.error == "Прокси не назначен"


def test_studio_login_already_ready(db_session, make_account, make_proxy, monkeypatch):
    proxy = make_proxy(label="px-yt")
    account = make_account(username="readyyt", proxy=proxy, platform="youtube")
    monkeypatch.setattr(
        "app.accounts.studio_login_service.playwright_browsers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.accounts.studio_login_service.studio_session_ready",
        lambda u, p: True,
    )
    out = run_studio_login(account, db_session)
    assert out.ok is True
    assert out.session_imported is True


def test_studio_login_headless_ok(db_session, make_account, make_proxy, monkeypatch):
    from app.behavior.studio_playwright import StudioLoginResult

    proxy = make_proxy(label="px-hl")
    account = make_account(username="hlyt", proxy=proxy, platform="youtube")
    account.password = "pass"
    db_session.commit()

    ready_calls = [False, True]

    def _ready(u, p):
        if ready_calls:
            return ready_calls.pop(0)
        return True

    monkeypatch.setattr("app.accounts.studio_login_service.studio_session_ready", _ready)
    monkeypatch.setattr(
        "app.accounts.studio_login_service.studio_login",
        lambda **k: StudioLoginResult(ok=True),
    )
    monkeypatch.setattr(
        "app.accounts.studio_login_service.playwright_browsers_available",
        lambda: True,
    )
    out = run_studio_login(account, db_session)
    assert out.ok is True


def test_studio_login_wrong_platform(db_session, make_account, make_proxy, monkeypatch):
    monkeypatch.setattr(
        "app.accounts.studio_login_service.playwright_browsers_available",
        lambda: True,
    )
    proxy = make_proxy(label="px-ig")
    account = make_account(username="igonly", proxy=proxy, platform="instagram")
    out = run_studio_login(account, db_session)
    assert out.ok is False
