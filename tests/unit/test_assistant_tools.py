"""Assistant tools: read (including secrets), create/update — never delete."""

from __future__ import annotations

from pathlib import Path

from datetime import datetime, timedelta, timezone

from app.assistant.chat import run_tool
from app.assistant.tools import ToolError, list_accounts, open_page, pause_account, plan_account
from app.db.models import AccountStatus, PipelineStatus, PlanJob, PostJob, PostJobStatus


def test_open_page_uses_this_panel_routes():
    opened = open_page("accounts")
    assert opened.path == "/accounts"
    opened = open_page("library")
    assert opened.path == "/publishing"


def test_open_page_refuses_unknown():
    try:
        open_page("oauth")
    except ToolError as exc:
        assert "нет" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_plan_account_queues_a_plan_job(db_session, make_account):
    account = make_account()
    out = plan_account(db_session, account.id, count=3, week=True)
    job = db_session.get(PlanJob, out["queued_plan_id"])
    assert job is not None
    assert job.count == 3
    assert job.spread_over_days == 7
    assert job.status is PipelineStatus.queued


def test_pause_does_not_touch_proxy_or_password(db_session, make_account):
    account = make_account(password="secret")
    proxy_id = account.proxy_id
    pause_account(db_session, account.id)
    db_session.refresh(account)
    assert account.status is AccountStatus.paused
    assert account.password == "secret"
    assert account.proxy_id == proxy_id


def test_run_tool_has_no_delete_tools(db_session):
    for name in ("delete_account", "delete_job", "delete_source"):
        try:
            run_tool(db_session, name, {"account_id": 1})
        except ToolError as exc:
            assert "нет" in str(exc)
        else:
            raise AssertionError(f"expected ToolError for {name}")


def test_run_tool_creates_proxy_then_youtube_account(db_session):
    from app.assistant.tools import list_accounts, list_proxies
    from app.db.models import Account, Proxy
    from sqlalchemy import select

    proxy_out, opened_px = run_tool(
        db_session,
        "create_proxy",
        {"label": "probe-yt-px", "url": "http://u:p@example:8000"},
    )
    assert opened_px is None
    assert proxy_out["id"] is not None
    assert proxy_out["label"] == "probe-yt-px"

    account_out, opened_acc = run_tool(
        db_session,
        "create_account",
        {
            "username": "probe_yt_user",
            "proxy_label": "probe-yt-px",
            "password": "unused",
            "platform": "youtube",
        },
    )
    assert opened_acc is None
    assert account_out["id"] is not None
    assert account_out["username"] == "probe_yt_user"
    assert account_out["platform"] == "youtube"

    labels = {row["label"] for row in list_proxies(db_session)}
    assert "probe-yt-px" in labels
    names = {row["username"] for row in list_accounts(db_session)}
    assert "probe_yt_user" in names
    stored = db_session.scalar(
        select(Account).where(Account.username == "probe_yt_user")
    )
    assert stored is not None
    assert db_session.get(Proxy, stored.proxy_id).label == "probe-yt-px"


def test_tool_specs_have_create_but_no_settings_writes():
    from app.assistant.chat import tool_specs

    names = {spec["function"]["name"] for spec in tool_specs()}
    assert "create_account" in names
    assert "create_proxy" in names
    assert "account_logs" in names
    assert "docker_logs" in names
    blob = " ".join(names).lower()
    for forbidden in (
        "entry_path",
        "master_password",
        "update_settings",
        "write_env",
        "update_entry_path",
        "set_master_password",
    ):
        assert forbidden not in blob


def test_run_tool_has_no_settings_or_env_write_tools(db_session):
    for name in (
        "update_entry_path",
        "update_master_password",
        "set_master_password",
        "update_settings",
        "write_env",
        "save_env",
    ):
        try:
            run_tool(db_session, name, {"path": "/x", "password": "y"})
        except ToolError as exc:
            assert "нет" in str(exc)
        else:
            raise AssertionError(f"expected ToolError for {name}")


def test_list_operators_reads_entry_path_without_changing_it(db_session):
    from app.panel.settings_store import get_or_create_panel_settings

    before = get_or_create_panel_settings(db_session).entry_path
    result, opened = run_tool(db_session, "list_operators", {})
    assert opened is None
    assert result["entry_path"] == before
    after = get_or_create_panel_settings(db_session).entry_path
    assert after == before


def test_list_operators_hides_gate_from_operator(db_session):
    import json

    from app.assistant.tools import list_operators
    from app.panel.settings_store import get_or_create_panel_settings

    secret = get_or_create_panel_settings(db_session).entry_path
    out = list_operators(db_session, as_owner=False)
    assert "entry_path" not in out
    assert "owner_token" not in out
    assert "operators" in out
    assert "how" in out
    leaked = secret in json.dumps(out)
    assert not leaked

    via_tool, opened = run_tool(db_session, "list_operators", {}, viewer_role="operator")
    assert opened is None
    assert "entry_path" not in via_tool
    assert "owner_token" not in via_tool


def test_open_account_and_post_use_panel_query(db_session, make_account, app_env):
    from app.assistant.tools import open_account, open_post

    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path=str(app_env.video_source_dir / "clip.mp4"),
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.queued,
        title="held",
    )
    db_session.add(job)
    db_session.commit()
    opened = open_account(db_session, account.id)
    assert opened.path == "/accounts"
    assert opened.query == {"id": str(account.id)}
    opened_post = open_post(db_session, job.id)
    assert opened_post.path == "/activity"
    assert opened_post.query == {"job": str(job.id)}


def test_enqueue_publish_from_library_file(db_session, make_account, app_env):
    from app.assistant.tools import enqueue_publish

    account = make_account()
    clip = Path(app_env.video_source_dir) / "clip.mp4"
    clip.write_bytes(b"not-really-video")
    out = enqueue_publish(db_session, account_id=account.id, filename="clip.mp4", title="Hello")
    job = db_session.get(PostJob, out["job_id"])
    assert job is not None
    assert job.title == "Hello"
    assert job.account_id == account.id


def test_list_accounts_includes_passwords(db_session, make_account):
    make_account(username="alice", password="hunter2")
    rows = list_accounts(db_session)
    assert rows
    assert rows[0]["password"] == "hunter2"
    assert "session_id" in rows[0]


def test_account_details_includes_secrets(db_session, make_account):
    from app.assistant.tools import account_details

    account = make_account(username="alice", password="hunter2")
    account.totp_seed = "JBSWY3DPEHPK3PXP"
    account.email_password = "imap-secret"
    db_session.commit()
    details = account_details(db_session, account.id)
    assert details["password"] == "hunter2"
    assert details["totp_seed"] == "JBSWY3DPEHPK3PXP"
    assert details["email_password"] == "imap-secret"
    assert details["proxy"]["url"]


def test_open_page_russian_aliases():
    assert open_page("прокси").path == "/accounts"
    assert open_page("аккаунты").path == "/accounts"
    assert open_page("библиотека").path == "/publishing"
    assert open_page("активность").path == "/activity"
    assert open_page("администрирование").path == "/administration"


def test_list_proxies_includes_url(db_session, make_account):
    from app.assistant.tools import list_proxies

    make_account(username="alice")
    rows = list_proxies(db_session)
    assert rows
    assert rows[0]["url"]
    assert rows[0]["label"]
    assert rows[0]["accounts"] >= 1


def test_list_clips_matches_filename(db_session):
    from app.assistant.tools import list_clips
    from app.db.models import AssetKind, AssetSource, MediaAsset

    db_session.add(
        MediaAsset(
            filename="ridge-fog.mp4",
            kind=AssetKind.video,
            source=AssetSource.generated,
            label="clip",
        )
    )
    db_session.commit()
    found = list_clips(db_session, query="ridge-fog")
    assert found[0]["filename"] == "ridge-fog.mp4"


def test_list_clips_matches_disk_filename(app_env, db_session):
    from app.assistant.tools import list_clips

    clip = Path(app_env.video_source_dir) / "qa_clip.mp4"
    clip.write_bytes(b"not-really-video")
    found = list_clips(db_session, query="qa_clip")
    assert found[0]["filename"] == "qa_clip.mp4"
    assert found[0]["on_disk"] is True


def test_list_errors_and_job_logs(db_session, make_account):
    from app.assistant.tools import job_logs, list_errors
    from app.db.models import (
        DiagnosticRun,
        DiagnosticRunKind,
        DiagnosticRunStatus,
        Event,
        EventLevel,
    )

    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path="clip.mp4",
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.failed,
        title="held",
        last_error="proxy timeout",
    )
    db_session.add(job)
    db_session.flush()
    db_session.add(
        Event(account_id=account.id, level=EventLevel.error, kind="publish", message="boom")
    )
    db_session.add(
        DiagnosticRun(
            kind=DiagnosticRunKind.publish_job,
            account_id=account.id,
            job_id=job.id,
            status=DiagnosticRunStatus.fail,
            summary="upload failed",
            lines_json='[{"ts":"2026-01-01T00:00:00Z","level":"error","step":"upload","message":"timeout"}]',
        )
    )
    db_session.commit()

    errors = list_errors(db_session)
    assert errors["failed_posts"][0]["last_error"] == "proxy timeout"
    assert errors["events"][0]["message"] == "boom"

    payload, opened = job_logs(db_session, job.id)
    assert opened.path == "/activity"
    assert opened.query == {"job": str(job.id)}
    assert payload["runs"][0]["lines"][0]["message"] == "timeout"


def test_account_logs_redacts_password_and_lists_login_runs(db_session, make_account):
    from app.assistant.chat import run_tool
    from app.assistant.tools import account_logs, list_errors
    from app.db.models import (
        DiagnosticRun,
        DiagnosticRunKind,
        DiagnosticRunStatus,
        Event,
        EventLevel,
    )

    account = make_account(username="logreader", password="super-secret-pw")
    db_session.add(
        DiagnosticRun(
            kind=DiagnosticRunKind.first_login,
            account_id=account.id,
            status=DiagnosticRunStatus.fail,
            summary="Неверный пароль",
            lines_json=(
                '[{"ts":"2026-01-01T00:00:00Z","level":"info","step":"account",'
                '"message":"Пароль: super-secret-pw"},'
                '{"ts":"2026-01-01T00:00:01Z","level":"error","step":"login",'
                '"message":"Неверный пароль"}]'
            ),
        )
    )
    db_session.add(
        Event(
            account_id=account.id,
            level=EventLevel.error,
            kind="first_login",
            message="Неверный пароль",
        )
    )
    db_session.commit()

    payload, opened = account_logs(db_session, account.id, kind="first_login")
    assert opened.path == "/accounts"
    assert opened.query == {"id": str(account.id)}
    messages = [line["message"] for line in payload["runs"][0]["lines"]]
    assert "Пароль: ***" in messages
    assert "super-secret-pw" not in str(payload)

    via_tool, _opened = run_tool(db_session, "account_logs", {"account_id": account.id})
    assert via_tool["username"] == "logreader"
    assert "super-secret-pw" not in str(via_tool)

    errors = list_errors(db_session)
    assert any(e["kind"] == "first_login" for e in errors["events"])

    try:
        account_logs(db_session, account.id, kind="nope")
    except ToolError as exc:
        assert "kind" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_create_and_update_proxy_and_account(db_session, make_proxy):
    from app.assistant.tools import attach_proxy, create_account, create_proxy, update_account, update_proxy

    proxy = create_proxy(db_session, label="mob-new", url="http://u:p@example:8000", country="US")
    assert proxy["url"] == "http://u:p@example:8000"
    updated = update_proxy(db_session, "mob-new", url="http://u:p@example:9000")
    assert updated["url"] == "http://u:p@example:9000"

    created = create_account(
        db_session,
        username="newbie",
        proxy_label="mob-new",
        password="first-pass",
    )
    assert created["password"] == "first-pass"
    assert created["username"] == "newbie"

    other = make_proxy(label="other-px", url="http://x:y@host:1")
    attached = attach_proxy(db_session, created["id"], other.label)
    assert attached["proxy_label"] == "other-px"

    changed = update_account(db_session, created["id"], password="second-pass", totp_seed="ABCD")
    assert changed["password"] == "second-pass"
    assert changed["totp_seed"] == "ABCD"


def test_create_accounts_two_usernames(db_session):
    from app.assistant.tools import create_accounts, create_proxy
    from app.db.models import Account
    from sqlalchemy import select

    create_proxy(db_session, label="mob-bulk", url="http://u:p@example:8000")
    out = create_accounts(
        db_session,
        [
            {"username": "ann", "proxy_label": "mob-bulk", "password": "p1"},
            {"username": "bob", "proxy_label": "mob-bulk", "password": "p2"},
        ],
    )
    assert out["failed"] == []
    assert {row["username"] for row in out["created"]} == {"ann", "bob"}
    names = {a.username for a in db_session.scalars(select(Account)).all()}
    assert {"ann", "bob"} <= names


def test_create_accounts_partial_bad_proxy(db_session):
    from app.assistant.tools import create_accounts, create_proxy

    create_proxy(db_session, label="mob-bulk", url="http://u:p@example:8000")
    out = create_accounts(
        db_session,
        [
            {"username": "ann", "proxy_label": "mob-bulk"},
            {"username": "bob", "proxy_label": "missing-px"},
        ],
    )
    assert len(out["created"]) == 1
    assert out["created"][0]["username"] == "ann"
    assert len(out["failed"]) == 1
    assert out["failed"][0]["item"] == "bob"
    assert "нет" in out["failed"][0]["ошибка"]


def test_create_accounts_asks_when_no_required_fields(db_session):
    from app.assistant.tools import create_accounts

    out = create_accounts(db_session, [{}, {"username": ""}])
    assert out["ask"] is True
    assert any("username" in q for q in out["questions"])


def test_create_proxies_partial_success(db_session):
    from app.assistant.tools import create_proxies

    out = create_proxies(
        db_session,
        [
            {"label": "px-a", "url": "http://u:p@example:1"},
            {"label": "px-b"},
        ],
    )
    assert len(out["created"]) == 1
    assert out["created"][0]["label"] == "px-a"
    assert len(out["failed"]) == 1
    assert "url" in out["failed"][0]["ошибка"]


def test_export_cookies_opens_download_query(db_session, make_account, app_env):
    from app.assistant.tools import export_cookies

    account = make_account(username="alice", session_id="k" * 40)
    payload, opened = export_cookies(db_session, account.id)
    assert opened.path == "/accounts"
    assert opened.query["id"] == str(account.id)
    assert opened.query["download"] == "cookies"
    assert payload["скачивается"] == "в браузере"


def test_export_fingerprint_txt_query(db_session, make_account, app_env):
    from app.accounts.device_factory import generate_fingerprint, save_fingerprint
    from app.assistant.tools import export_fingerprint

    account = make_account(username="fpuser")
    save_fingerprint("fpuser", generate_fingerprint(country="US"))
    payload, opened = export_fingerprint(db_session, account.id, format="txt")
    assert opened.query["download"] == "fingerprint"
    assert opened.query["format"] == "txt"
    assert payload["format"] == "txt"


def test_import_cookies_sets_session_id(db_session, make_account, app_env):
    from app.assistant.tools import import_cookies

    account = make_account(username="imp")
    sid = "a" * 40
    out = import_cookies(
        db_session,
        account.id,
        data=[{"name": "sessionid", "value": sid, "domain": ".instagram.com"}],
    )
    assert out["session_id"] == sid
    db_session.refresh(account)
    assert account.session_id == sid


def test_import_fingerprint_saves_device(db_session, make_account, app_env):
    from app.accounts.device_factory import generate_fingerprint, load_fingerprint
    from app.assistant.tools import import_fingerprint

    account = make_account(username="fpin")
    fp = generate_fingerprint(country="US")
    out = import_fingerprint(db_session, account.id, data=fp.to_dict())
    assert out["saved"] is True
    loaded = load_fingerprint("fpin")
    assert loaded is not None
    assert loaded.user_agent == fp.user_agent


def test_test_proxies_partial_labels(db_session, make_proxy, monkeypatch):
    from types import SimpleNamespace

    from app.assistant.tools import test_proxies

    make_proxy(label="ok-px")
    make_proxy(label="bad-px")

    def fake_health(_db, proxy):
        if proxy.label == "ok-px":
            return True, SimpleNamespace(ip="1.1.1.1", country="US"), None
        return False, None, "timeout"

    monkeypatch.setattr("app.proxies.pool.health_check_record", fake_health)
    out = test_proxies(db_session, ["ok-px", "bad-px"])
    assert len(out["checked"]) == 1
    assert out["checked"][0]["label"] == "ok-px"
    assert len(out["failed"]) == 1
    assert out["failed"][0]["label"] == "bad-px"


def test_test_connections_two_accounts(db_session, make_account, monkeypatch):
    from types import SimpleNamespace

    from app.assistant.tools import test_connections

    ann = make_account(username="ann")
    bob = make_account(username="bob")

    def fake_run(account, db, probe_mobile=False):
        ok = account.username == "ann"
        return SimpleNamespace(
            username=account.username,
            overall_ok=ok,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=ok, error=None if ok else "down"),
            instagram_auth=SimpleNamespace(ok=ok, error=None if ok else "auth"),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_run)
    out = test_connections(db_session, [ann.id, bob.id])
    assert len(out["checked"]) == 1
    assert out["checked"][0]["username"] == "ann"
    assert len(out["failed"]) == 1
    assert out["failed"][0]["username"] == "bob"


def test_publish_now_does_not_enqueue_when_connection_fails(
    db_session, make_account, monkeypatch
):
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.assistant.tools import publish_now
    from app.db.models import PostJob

    account = make_account(username="alice")

    def fake_run(account, db, probe_mobile=False):
        return SimpleNamespace(
            username=account.username,
            overall_ok=False,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=False, error="proxy down"),
            instagram_auth=SimpleNamespace(ok=False, error="skip"),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_run)
    out = publish_now(db_session, account.id, filename="clip.mp4")
    assert out["опубликовано"] is False
    assert db_session.scalars(select(PostJob)).all() == []


def test_publish_now_enqueues_when_connection_ok(
    db_session, make_account, monkeypatch, app_env
):
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.assistant.tools import publish_now
    from app.config import settings
    from app.db.models import PostJob

    account = make_account(username="alice")
    clip = settings.video_source_dir / "clip.mp4"
    clip.write_bytes(b"fake")

    def fake_run(account, db, probe_mobile=False):
        return SimpleNamespace(
            username=account.username,
            overall_ok=True,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=True, error=None),
            instagram_auth=SimpleNamespace(ok=True, error=None),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_run)
    out = publish_now(db_session, account.id, filename="clip.mp4")
    assert out["опубликовано"] is True
    jobs = list(db_session.scalars(select(PostJob)).all())
    assert len(jobs) == 1
    assert jobs[0].account_id == account.id


def test_export_youtube_cookies_filters_domains(db_session, make_account, app_env):
    from app.accounts.cookie_formats import export_dolphin_cookies
    from app.accounts.playwright_session import save_playwright_state
    from app.assistant.tools import export_cookies
    from app.db.models import Platform

    account = make_account(username="ytuser", platform=Platform.youtube)
    save_playwright_state(
        "ytuser",
        {
            "cookies": [
                {"name": "SID", "value": "abc", "domain": ".youtube.com"},
                {"name": "sessionid", "value": "k" * 40, "domain": ".instagram.com"},
            ],
            "origins": [],
        },
    )
    cookies, source = export_dolphin_cookies("ytuser", platform="youtube")
    assert source == "playwright"
    assert all("instagram" not in (c.get("domain") or "").lower() for c in cookies)
    assert any(c["name"] == "SID" for c in cookies)
    payload, opened = export_cookies(db_session, account.id)
    assert opened.query["download"] == "cookies"


def test_get_session_youtube_lists_names_without_values(db_session, make_account, app_env):
    from app.accounts.playwright_session import save_playwright_state
    from app.assistant.tools import get_session
    from app.db.models import Platform

    account = make_account(username="ytget", platform=Platform.youtube)
    save_playwright_state(
        "ytget",
        {"cookies": [{"name": "SID", "value": "secret", "domain": ".youtube.com"}], "origins": []},
    )
    out = get_session(db_session, account.id)
    assert out["playwright_state"] is True
    assert "SID" in out["names"]
    assert "secret" not in str(out)


def test_first_login_and_mint_refuse_youtube(db_session, make_account):
    from app.assistant.tools import ToolError, first_login, mint_mobile_session
    from app.db.models import Platform

    account = make_account(username="ytrefuse", platform=Platform.youtube)
    try:
        first_login(db_session, account.id)
    except ToolError as exc:
        assert "Instagram" in str(exc)
    else:
        raise AssertionError("expected ToolError")
    try:
        mint_mobile_session(db_session, account.id)
    except ToolError as exc:
        assert "Instagram" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_update_account_session_id_refuses_youtube(db_session, make_account):
    from app.assistant.tools import ToolError, update_account
    from app.db.models import Platform

    account = make_account(username="ytsid", platform=Platform.youtube)
    try:
        update_account(db_session, account.id, session_id="a" * 40)
    except ToolError as exc:
        assert "Instagram" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_publish_now_youtube_skips_job_without_studio_cookies(
    db_session, make_account, monkeypatch
):
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.assistant.tools import publish_now
    from app.db.models import Platform, PostJob

    account = make_account(username="ytpub", platform=Platform.youtube)

    def fake_run(account, db, probe_mobile=False):
        return SimpleNamespace(
            username=account.username,
            overall_ok=False,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=True, error=None),
            instagram_auth=SimpleNamespace(ok=False, error="Playwright state не найден"),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_run)
    out = publish_now(db_session, account.id, filename="clip.mp4")
    assert out["опубликовано"] is False
    assert db_session.scalars(select(PostJob)).all() == []


def test_publish_now_youtube_enqueues_short(
    db_session, make_account, monkeypatch, app_env
):
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.assistant.tools import publish_now
    from app.config import settings
    from app.db.models import Platform, PostJob, PostType

    account = make_account(username="ytok", platform=Platform.youtube)
    clip = settings.video_source_dir / "clip.mp4"
    clip.write_bytes(b"fake")

    def fake_run(account, db, probe_mobile=False):
        return SimpleNamespace(
            username=account.username,
            overall_ok=True,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=True, error=None),
            instagram_auth=SimpleNamespace(ok=True, error=None),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_run)
    out = publish_now(db_session, account.id, filename="clip.mp4")
    assert out["опубликовано"] is True
    jobs = list(db_session.scalars(select(PostJob)).all())
    assert len(jobs) == 1
    assert jobs[0].post_type is PostType.youtube_short


def test_publish_now_tiktok_enqueues_post(
    db_session, make_account, monkeypatch, app_env
):
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.assistant.tools import publish_now
    from app.config import settings
    from app.db.models import Platform, PostJob, PostType

    account = make_account(username="ttok", platform=Platform.tiktok)
    clip = settings.video_source_dir / "clip.mp4"
    clip.write_bytes(b"fake")

    def fake_run(account, db, probe_mobile=False):
        return SimpleNamespace(
            username=account.username,
            overall_ok=True,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=True, error=None),
            instagram_auth=SimpleNamespace(ok=True, error=None),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_run)
    out = publish_now(db_session, account.id, filename="clip.mp4")
    assert out["опубликовано"] is True
    jobs = list(db_session.scalars(select(PostJob)).all())
    assert len(jobs) == 1
    assert jobs[0].post_type is PostType.tiktok


def test_export_fingerprint_refuses_youtube(db_session, make_account):
    from app.assistant.tools import ToolError, export_fingerprint, import_fingerprint
    from app.db.models import Platform

    account = make_account(username="ytfp", platform=Platform.youtube)
    try:
        export_fingerprint(db_session, account.id)
    except ToolError as exc:
        assert "Instagram" in str(exc)
    else:
        raise AssertionError("expected ToolError")
    try:
        import_fingerprint(db_session, account.id, data={"android_device_id": "x"})
    except ToolError as exc:
        assert "Instagram" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_test_connections_probe_mobile_does_not_abort_studio(
    db_session, make_account, monkeypatch
):
    from types import SimpleNamespace

    from app.assistant.tools import test_connections
    from app.db.models import Platform

    ig = make_account(username="igok")
    yt = make_account(username="ytmix", platform=Platform.youtube)

    def fake_run(account, db, probe_mobile=False):
        return SimpleNamespace(
            username=account.username,
            overall_ok=True,
            proxy_label="px",
            proxy_health=SimpleNamespace(ok=True, error=None),
            instagram_auth=SimpleNamespace(ok=True, error=None),
            run_id=1,
        )

    monkeypatch.setattr("app.accounts.connection_test.run_account_connection_test", fake_run)
    out = test_connections(db_session, [ig.id, yt.id], probe_mobile=True)
    assert len(out["checked"]) == 1
    assert out["checked"][0]["username"] == "igok"
    assert len(out["failed"]) == 1
    assert out["failed"][0]["username"] == "ytmix"
    assert "Instagram" in (out["failed"][0].get("error") or "")


def test_describe_covers_session_and_publish_tools():
    from app.assistant.chat import describe

    assert describe("export_cookies", {"account_id": 1}) == "выгружаю cookies"
    assert describe("publish_now", {"account_id": 1, "filename": "clip.mp4"}) == (
        "проверяю и ставлю публикацию"
    )
    assert describe("test_proxies", {}) == "проверяю прокси"
    assert describe("diagnose", {}) == "смотрю постинг, вход и прокси"


def test_read_project_file_stays_inside_repo():
    from app.assistant.tools import ToolError, read_project_file

    readme = read_project_file("README.md")
    assert "text" in readme
    try:
        read_project_file("..")
    except ToolError as exc:
        assert "внутри" in str(exc) or "не" in str(exc)
    else:
        raise AssertionError("expected ToolError for parent path")


def test_list_operators_explains_access(db_session):
    from app.assistant.tools import list_operators

    out = list_operators(db_session)
    assert "entry_path" in out
    assert "оператор" in out["how"].lower() or "доступ" in out["how"].lower()


def test_ask_operator_returns_questions(db_session):
    result, opened = run_tool(
        db_session,
        "ask_operator",
        {"questions": ["какой username?", "какой proxy_label?"], "reason": "создать аккаунт"},
    )
    assert opened is None
    assert result["ask"] is True
    assert result["questions"] == ["какой username?", "какой proxy_label?"]
    assert result["fields"] == []
    assert "создать" in result["why"]


def test_ask_operator_fields_fill_questions(db_session):
    result, opened = run_tool(
        db_session,
        "ask_operator",
        {
            "reason": "добавить аккаунт",
            "fields": [
                {"id": "proxy_label", "label": "Метка прокси", "kind": "text"},
                {"id": "proxy_url", "label": "URL прокси", "kind": "text"},
                {
                    "id": "platform",
                    "label": "Площадка",
                    "kind": "select",
                    "options": ["instagram", "youtube", "tiktok"],
                },
                {"id": "username", "label": "Username", "kind": "text"},
                {"id": "password", "label": "Пароль", "kind": "password"},
            ],
        },
    )
    assert opened is None
    assert result["ask"] is True
    assert result["questions"] == [
        "Метка прокси",
        "URL прокси",
        "Площадка",
        "Username",
        "Пароль",
    ]
    assert result["fields"][0]["id"] == "proxy_label"
    assert result["fields"][2]["kind"] == "select"
    assert result["fields"][4]["kind"] == "password"


def test_ask_operator_rejects_empty(db_session):
    try:
        run_tool(db_session, "ask_operator", {"questions": []})
    except ToolError as exc:
        assert "вопрос" in str(exc) or "field" in str(exc)
    else:
        raise AssertionError("expected ToolError")

def test_page_guide_returns_another_page_section(db_session):
    result, opened = run_tool(db_session, "page_guide", {"page": "operators"})
    assert opened is None
    assert result["page"] == "Доступы"
    assert result["path"] == "/operators"
    assert "Доступы" in result["guide"]
    assert "Сгенерировать пароль" in result["guide"]


def test_stream_emits_ask_and_stops(db_session, monkeypatch):
    from app.assistant import chat
    from app.config import Settings

    monkeypatch.setattr(chat, "_prepare_runtime", lambda settings: None)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(chat, "http_client", lambda *a, **k: FakeClient())

    def fake_complete(client, settings, thread, said, **_kwargs):
        if False:
            yield chat.Step(kind="token", text="")
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {
                        "name": "ask_operator",
                        "arguments": '{"questions": ["какой username?"], "reason": "создать аккаунт"}',
                    },
                }
            ],
        }

    monkeypatch.setattr(chat, "_complete", fake_complete)
    settings = Settings(_env_file=None)
    steps = list(
        chat.stream(
            db_session,
            [{"role": "user", "content": "добавь аккаунт"}],
            settings=settings,
            page="/accounts",
        )
    )
    asks = [s for s in steps if isinstance(s, chat.Step) and s.kind == "ask"]
    answers = [s for s in steps if isinstance(s, chat.Answer)]
    assert asks and asks[0].questions == ["какой username?"]
    assert answers[-1].asks == ["какой username?"]
    assert "уточнен" in answers[-1].reply.lower() or "создать" in answers[-1].reply.lower()
    assert answers[-1].used == ["ask_operator"]


def test_stream_tool_step_includes_name(db_session, monkeypatch):
    from app.assistant import chat
    from app.config import Settings

    monkeypatch.setattr(chat, "_prepare_runtime", lambda settings: None)

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
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {"name": "list_accounts", "arguments": "{}"},
                    }
                ],
            }
        return {"role": "assistant", "content": "ок"}

    monkeypatch.setattr(chat, "_complete", fake_complete)
    settings = Settings(_env_file=None)
    steps = list(
        chat.stream(
            db_session,
            [{"role": "user", "content": "сколько аккаунтов?"}],
            settings=settings,
        )
    )
    tools = [s for s in steps if isinstance(s, chat.Step) and s.kind == "tool"]
    assert tools
    assert tools[0].name == "list_accounts"
    assert tools[0].text == "смотрю аккаунты"


def test_stream_done_includes_created_account_ids(db_session, monkeypatch):
    from app.assistant import chat
    from app.config import Settings

    monkeypatch.setattr(chat, "_prepare_runtime", lambda settings: None)

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
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "create_account",
                            "arguments": '{"username": "ann", "proxy_label": "px"}',
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "добавил"}

    monkeypatch.setattr(chat, "_complete", fake_complete)
    monkeypatch.setattr(
        chat,
        "run_tool",
        lambda db, name, args, **kw: ({"id": 42, "username": "ann"}, None),
    )
    settings = Settings(_env_file=None)
    steps = list(
        chat.stream(
            db_session,
            [{"role": "user", "content": "добавь аккаунт"}],
            settings=settings,
        )
    )
    answers = [s for s in steps if isinstance(s, chat.Answer)]
    assert answers[-1].created["accounts"] == [42]


def test_diagnose_without_app_log_does_not_crash(db_session, monkeypatch):
    from app.assistant.tools import diagnose
    from app.services.runtime import Runtime

    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    out = diagnose(db_session)
    assert out["app_log"] is None
    assert out["app_log_reason"]
    assert "worker" in out
    assert out["ollama"]["reachable"] is False
    assert "errors" in out
    assert "render_backends" in out


def test_docker_logs_without_cli(monkeypatch):
    from app.assistant.tools import docker_logs

    def boom(*_a, **_k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("app.assistant.tools.subprocess.run", boom)
    monkeypatch.setattr(
        "app.assistant.tools._docker_engine_logs",
        lambda *_a, **_k: {"available": False, "reason": "нет /var/run/docker.sock", "lines": []},
    )
    out = docker_logs("reels-api")
    assert out["available"] is False
    assert "Docker CLI" in out["reason"]
    assert out["lines"] == []


def test_docker_logs_falls_back_to_engine(monkeypatch):
    from app.assistant.tools import docker_logs

    def boom(*_a, **_k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("app.assistant.tools.subprocess.run", boom)
    monkeypatch.setattr(
        "app.assistant.tools._docker_engine_logs",
        lambda container, tail: {
            "available": True,
            "lines": [f"{container} started"],
        },
    )
    out = docker_logs("reels-api")
    assert out["available"] is True
    assert out["source"] == "engine"
    assert out["service"] == "reels-api"
    assert out["lines"] == ["insta-reels-api started"]


def test_diagnose_tails_app_log(db_session, monkeypatch):
    from app.assistant.tools import diagnose
    from app.config import settings
    from app.services.runtime import Runtime

    log_file = settings.log_file
    assert log_file is not None
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("one\ntwo\nthree\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    out = diagnose(db_session, tail=2)
    assert out["app_log"] == ["two", "three"]
    assert out["app_log_reason"] is None
    assert "posting" in out


def test_diagnose_puts_hints_before_app_log_and_caps_default_tail(
    db_session, monkeypatch
):
    import json

    from app.assistant.tools import DIAGNOSE_LOG_TAIL, diagnose
    from app.config import settings
    from app.services.runtime import Runtime

    log_file = settings.log_file
    assert log_file is not None
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("\n".join(f"L{i}" for i in range(40)) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    out = diagnose(db_session)
    assert list(out)[0] == "hints"
    assert list(out)[-2:] == ["app_log", "app_log_reason"]
    assert len(out["app_log"]) == DIAGNOSE_LOG_TAIL
    blob = json.dumps(out, ensure_ascii=False)
    assert blob.index('"hints"') < blob.index('"app_log"')


def test_diagnose_caps_missing_session_list(db_session, make_account, monkeypatch):
    from app.assistant.tools import SNAPSHOT_LIST_LIMIT, diagnose
    from app.services.runtime import Runtime
    from app.services.worker_control import Running

    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    monkeypatch.setattr("app.services.worker_control.status", lambda: Running(False))
    for i in range(SNAPSHOT_LIST_LIMIT + 1):
        make_account(username=f"miss{i}")
    out = diagnose(db_session)
    login = out["login"]
    assert len(login["missing_session"]) == SNAPSHOT_LIST_LIMIT
    assert login["missing_session_omitted"] == 1
    assert any("first_login" in hint for hint in login["hints"])
    assert any("first_login" in hint for hint in out["hints"])


def test_diagnose_posting_snapshot_stale_worker_and_challenge(
    db_session, make_account, make_proxy, app_env, monkeypatch
):
    from app.assistant.tools import diagnose
    from app.db.models import AccountStatus
    from app.services.runtime import Runtime
    from app.services.worker_control import Running

    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    monkeypatch.setattr("app.services.worker_control.status", lambda: Running(False))

    proxy = make_proxy(label="dead-px", is_healthy=False)
    account = make_account(username="challenged", proxy=proxy, status=AccountStatus.challenge)
    due = PostJob(
        account_id=account.id,
        source_video_path=str(app_env.video_source_dir / "clip.mp4"),
        scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
        status=PostJobStatus.queued,
        title="due",
    )
    later = PostJob(
        account_id=account.id,
        source_video_path=str(app_env.video_source_dir / "clip.mp4"),
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
        status=PostJobStatus.queued,
        title="later",
    )
    db_session.add_all([due, later])
    db_session.commit()

    out = diagnose(db_session)
    posting = out["posting"]
    assert posting["queued_due"] == 1
    assert posting["posts_by_status"]["queued"] == 2
    assert posting["awaiting_review"] == 0
    assert posting["accounts_not_active"] == [
        {"id": account.id, "username": "challenged", "status": "challenge"}
    ]
    assert posting["proxies_unhealthy"] == [{"id": proxy.id, "label": "dead-px"}]
    assert any("start_worker" in hint for hint in posting["hints"])
    assert any("account_logs" in hint for hint in posting["hints"])
    assert any("test_proxy" in hint for hint in posting["hints"])
    assert out["worker"]["foreign_alive"] is False
    assert not any("очередь должна ехать" in hint for hint in posting["hints"])


def test_diagnose_foreign_worker_queued_due_does_not_ask_start(
    db_session, make_account, app_env, monkeypatch
):
    from app.assistant.tools import diagnose
    from app.db.models import WorkerBeat
    from app.services.runtime import Runtime
    from app.services.worker_control import Running

    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    monkeypatch.setattr("app.services.worker_control.status", lambda: Running(False))
    db_session.add(
        WorkerBeat(
            name="worker",
            seen_at=datetime.now(timezone.utc),
            period_seconds=20.0,
            note="docker",
        )
    )
    account = make_account()
    db_session.add(
        PostJob(
            account_id=account.id,
            source_video_path=str(app_env.video_source_dir / "clip.mp4"),
            scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
            status=PostJobStatus.queued,
            title="due",
        )
    )
    db_session.commit()

    out = diagnose(db_session)
    assert out["worker"]["foreign_alive"] is True
    assert out["worker"]["ours_alive"] is False
    assert out["worker"]["stale"] is False
    assert out["posting"]["queued_due"] == 1
    hints = out["posting"]["hints"]
    assert any("очередь должна ехать" in hint for hint in hints)
    assert any("не start_worker" in hint for hint in hints)
    assert not any("мёртвом воркере" in hint for hint in hints)


def test_diagnose_posting_awaiting_review_hint(db_session, make_account, app_env, monkeypatch):
    from app.assistant.tools import diagnose
    from app.services.runtime import Runtime
    from app.services.worker_control import Running

    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    monkeypatch.setattr("app.services.worker_control.status", lambda: Running(True, 1))
    from app.db.models import WorkerBeat

    beat = WorkerBeat(
        name="worker",
        seen_at=datetime.now(timezone.utc),
        period_seconds=20,
        pid=1,
        note="",
    )
    db_session.add(beat)
    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path=str(app_env.video_source_dir / "clip.mp4"),
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.awaiting_review,
        title="hold",
    )
    failed = PostJob(
        account_id=account.id,
        source_video_path=str(app_env.video_source_dir / "clip.mp4"),
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.failed,
        title="boom",
        last_error="ffmpeg died",
    )
    db_session.add_all([job, failed])
    db_session.commit()

    out = diagnose(db_session)
    posting = out["posting"]
    assert posting["awaiting_review"] == 1
    assert posting["queued_due"] == 0
    assert any("approve_job" in hint for hint in posting["hints"])
    assert any("job_logs" in hint for hint in posting["hints"])
    assert not any("start_worker" in hint for hint in posting["hints"])


def test_diagnose_login_and_proxy_snapshots(
    db_session, make_account, make_proxy, monkeypatch
):
    from app.assistant.tools import diagnose
    from app.db.models import (
        Account,
        AccountStatus,
        DiagnosticRun,
        DiagnosticRunKind,
        DiagnosticRunStatus,
        Platform,
    )
    from app.services.runtime import Runtime
    from app.services.worker_control import Running

    monkeypatch.setattr(
        "app.services.runtime.probe",
        lambda settings=None: Runtime(reachable=False, base_url="http://x", detail="test"),
    )
    monkeypatch.setattr("app.services.worker_control.status", lambda: Running(False))

    proxy = make_proxy(label="dead-px", is_healthy=False, country="US")
    proxy.last_geo_country = "DE"
    proxy.last_checked_at = datetime.now(timezone.utc)
    db_session.commit()

    challenged = make_account(username="challenged", proxy=proxy, status=AccountStatus.challenge)
    run = DiagnosticRun(
        kind=DiagnosticRunKind.first_login,
        account_id=challenged.id,
        status=DiagnosticRunStatus.fail,
        summary="Instagram не выдал sessionid — splash",
    )
    lonely = Account(username="noproxy", password="x")
    studio = make_account(username="ytno", platform=Platform.youtube)
    db_session.add_all([run, lonely])
    db_session.commit()

    out = diagnose(db_session)
    login = out["login"]
    proxies = out["proxies"]

    assert any(row["username"] == "challenged" and row["status"] == "challenge" for row in login["not_active"])
    assert login["failed_runs"]
    assert login["failed_runs"][0]["kind"] == "first_login"
    assert "splash" in (login["failed_runs"][0]["summary"] or "")
    assert any(row["username"] == "noproxy" for row in login["no_proxy"])
    assert any(row["username"] == "challenged" and row["platform"] == "instagram" for row in login["missing_session"])
    assert any(row["username"] == "ytno" and row["platform"] == "youtube" for row in login["missing_session"])
    assert any("account_logs" in hint for hint in login["hints"])
    assert any("first_login" in hint for hint in login["hints"])
    assert any("attach_proxy" in hint for hint in login["hints"])

    assert proxies["unhealthy"]
    assert proxies["unhealthy"][0]["label"] == "dead-px"
    assert proxies["geo_mismatch"]
    assert proxies["geo_mismatch"][0]["advertised_country"] == "US"
    assert proxies["geo_mismatch"][0]["last_geo_country"] == "DE"
    assert any(row["username"] == "challenged" for row in proxies["accounts_on_unhealthy"])
    assert any("test_proxy" in hint for hint in proxies["hints"])
    assert any("geo_mismatch" in hint for hint in proxies["hints"])
    assert "url" not in proxies["unhealthy"][0]
    assert "session_id" not in login["missing_session"][0]


def test_tail_log_reads_from_end_not_whole_file(tmp_path, monkeypatch):
    from pathlib import Path

    from app.assistant.tools import _tail_log

    log = tmp_path / "app.log"
    log.write_text("\n".join(f"L{i}" for i in range(4000)) + "\n", encoding="utf-8")

    def _forbid_read_text(self, *args, **kwargs):
        raise AssertionError("must not read the whole log file")

    monkeypatch.setattr(Path, "read_text", _forbid_read_text)
    lines, reason = _tail_log(log, 3)
    assert reason is None
    assert lines == ["L3997", "L3998", "L3999"]


def test_docker_logs_refuses_unknown_service():
    from app.assistant.tools import docker_logs

    try:
        docker_logs("oauth")
    except ToolError as exc:
        assert "нет" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_decode_docker_log_stream_multiplexed():
    from app.assistant.tools import _decode_docker_log_stream

    payload = b"hello\n"
    header = bytes([1, 0, 0, 0]) + len(payload).to_bytes(4, "big")
    assert _decode_docker_log_stream(header + payload) == "hello\n"
    assert _decode_docker_log_stream(b"plain text") == "plain text"


def test_chat_body_enables_think():
    from app.assistant.chat import _chat_body
    from app.config import Settings

    settings = Settings(_env_file=None)
    body = _chat_body(settings, [], include_think=True)
    assert body["think"] is True
    assert body["options"]["num_ctx"] == 8192
    assert body["temperature"] == 0.1
    assert "think" not in _chat_body(settings, [], include_think=False)


def test_approve_retry_and_cancel_job(db_session, make_account):
    from app.assistant.tools import approve_job, cancel_job, retry_job

    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path="clip.mp4",
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.awaiting_review,
        title="held",
    )
    db_session.add(job)
    db_session.commit()
    approved = approve_job(db_session, job.id)
    assert approved["status"] == "queued"

    asked = cancel_job(db_session, job.id)
    assert asked["ask"] is True
    cancelled = cancel_job(db_session, job.id, confirm=True)
    assert cancelled["status"] == "cancelled"

    retried = retry_job(db_session, job.id)
    assert retried["status"] == "queued"


def test_start_worker_skips_when_foreign_heartbeat(db_session, monkeypatch):
    from app.assistant.tools import start_worker
    from app.db.models import WorkerBeat
    from app.services.worker_control import Running

    monkeypatch.setattr("app.services.worker_control.status", lambda: Running(False))
    def _no_start():
        raise AssertionError("must not spawn")

    monkeypatch.setattr("app.services.worker_control.start", _no_start)
    db_session.add(
        WorkerBeat(
            name="worker",
            seen_at=datetime.now(timezone.utc),
            period_seconds=20.0,
            note="docker",
        )
    )
    db_session.commit()
    out = start_worker(db_session)
    assert out["skipped"] is True
    assert out["ours"] is False
    assert out["running"] is True
    assert "start не нужен" in (out.get("сообщение") or "")


def test_stop_worker_asks_before_stopping(db_session):
    from app.assistant.tools import stop_worker

    asked = stop_worker(db_session)
    assert asked["ask"] is True
    try:
        stop_worker(db_session, confirm=True)
    except ToolError as exc:
        assert "запустила сама" in str(exc)
    else:
        raise AssertionError("expected ToolError when panel did not start the worker")


def test_take_backup_writes_a_copy(db_session, app_env):
    from pathlib import Path

    from app.assistant.tools import take_backup
    from app.config import get_settings

    out = take_backup()
    assert out["name"].startswith("app-")
    assert (Path(get_settings().backup_dir) / out["name"]).is_file()


def test_recent_talk_keeps_last_eight():
    from app.assistant.chat import _recent_talk

    msgs = [{"role": "user", "content": str(i)} for i in range(20)]
    assert [m["content"] for m in _recent_talk(msgs)] == [str(i) for i in range(12, 20)]


def test_create_render_without_key_quotes_healthcheck(db_session, monkeypatch):
    from app.assistant.tools import ToolError, create_render
    from app.config import settings

    monkeypatch.setattr(settings, "fal_api_key", "")
    monkeypatch.setattr(settings, "hf_token", "")
    monkeypatch.setattr(settings, "pollinations_video_url", "")
    monkeypatch.setattr(settings, "wan_base_url", "")
    monkeypatch.setattr(settings, "hf_space_id", "")
    try:
        create_render(db_session, prompt="туман над лесом")
    except ToolError as exc:
        assert "не настроен" in str(exc)
        assert "API-ключ" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_create_render_without_prompt_asks(db_session):
    result, opened = run_tool(db_session, "create_render", {})
    assert opened is None
    assert result["ask"] is True
    assert result["questions"]


def test_generate_wan_queues_local(db_session, monkeypatch):
    from app.assistant.chat import run_tool
    from app.config import settings
    from app.db.models import GenerationJob

    monkeypatch.setattr(settings, "wan_base_url", "http://wan/generate")
    result, opened = run_tool(
        db_session,
        "generate_wan",
        {"prompt": "туман над лесом", "seed": 7, "duration_s": 5},
    )
    job = db_session.get(GenerationJob, result["id"])
    assert job is not None
    assert job.backend == "local"
    assert job.seed == 7
    assert job.prompt == "туман над лесом"
    assert result["page"] == "/renders"
    assert opened is not None
    assert opened.path == "/renders"


def test_generate_wan_without_prompt_asks(db_session):
    from app.assistant.chat import run_tool

    result, opened = run_tool(db_session, "generate_wan", {})
    assert opened is None
    assert result["ask"] is True


def test_create_render_queues_when_key_set(db_session, monkeypatch):
    from app.assistant.tools import create_render
    from app.config import settings
    from app.db.models import GenerationJob

    monkeypatch.setattr(settings, "fal_api_key", "k")
    out = create_render(db_session, prompt="туман над лесом")
    job = db_session.get(GenerationJob, out["id"])
    assert job is not None
    assert job.prompt == "туман над лесом"
    assert job.status is PipelineStatus.queued
    assert job.backend == "auto"


def test_create_render_hf_without_fal_queues_auto(db_session, monkeypatch):
    from app.assistant.tools import create_render
    from app.config import settings
    from app.db.models import GenerationJob

    monkeypatch.setattr(settings, "fal_api_key", "")
    monkeypatch.setattr(settings, "hf_token", "hf-test")
    monkeypatch.setattr(settings, "pollinations_video_url", "")
    monkeypatch.setattr(settings, "wan_base_url", "")
    monkeypatch.setattr(settings, "hf_space_id", "")
    out = create_render(db_session, prompt="туман над лесом")
    job = db_session.get(GenerationJob, out["id"])
    assert job is not None
    assert job.backend == "auto"


def test_create_render_explicit_fal_without_key(db_session, monkeypatch):
    from app.assistant.tools import ToolError, create_render
    from app.config import settings

    monkeypatch.setattr(settings, "fal_api_key", "")
    monkeypatch.setattr(settings, "hf_token", "hf-test")
    try:
        create_render(db_session, prompt="туман", backend="fal")
    except ToolError as exc:
        assert "fal" in str(exc)
        assert "API-ключ" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_list_render_backends_reports_health(monkeypatch):
    from app.assistant.tools import list_render_backends
    from app.config import settings

    monkeypatch.setattr(settings, "fal_api_key", "k")
    monkeypatch.setattr(settings, "hf_token", "")
    rows = list_render_backends()
    names = [row["name"] for row in rows]
    assert "auto" in names
    assert "fal" in names
    fal = next(row for row in rows if row["name"] == "fal")
    assert fal["healthy"] is True


def test_compose_without_clips_asks(db_session):
    from app.assistant.tools import compose

    out = compose(db_session, clip_ids=[])
    assert out["ask"] is True
    assert "клип" in " ".join(out["questions"]).lower()


def test_compose_queues_two_clips(db_session):
    from app.assistant.tools import compose
    from app.db.models import AssetKind, AssetSource, Composition, MediaAsset

    first = MediaAsset(filename="join-a.mp4", kind=AssetKind.video, source=AssetSource.upload)
    second = MediaAsset(filename="join-b.mp4", kind=AssetKind.video, source=AssetSource.upload)
    db_session.add_all([first, second])
    db_session.commit()
    out = compose(db_session, clip_ids=[first.id, second.id], post_title="join")
    job = db_session.get(Composition, out["id"])
    assert job is not None
    assert job.status is PipelineStatus.queued
    assert out["clips"] == 2


def test_enqueue_publish_writes_scheduled_for(db_session, make_account, app_env):
    from app.assistant.tools import enqueue_publish

    account = make_account()
    clip = Path(app_env.video_source_dir) / "clip.mp4"
    clip.write_bytes(b"not-really-video")
    when = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
    out = enqueue_publish(
        db_session,
        account_id=account.id,
        filename="clip.mp4",
        title="Hello",
        when=when.isoformat(),
        caption="caption text",
        post_type="reel",
    )
    job = db_session.get(PostJob, out["job_id"])
    assert job is not None
    assert job.scheduled_for.replace(tzinfo=timezone.utc) == when
    assert job.caption_template == "caption text"
    assert out["scheduled_for"].startswith("2026-09-12T18:00:00")


def test_reschedule_job_moves_slot(db_session, make_account):
    from app.assistant.tools import reschedule_job

    account = make_account()
    job = PostJob(
        account_id=account.id,
        source_video_path="clip.mp4",
        scheduled_for=datetime.now(timezone.utc),
        status=PostJobStatus.queued,
        title="held",
    )
    db_session.add(job)
    db_session.commit()
    when = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
    out = reschedule_job(db_session, job.id, when=when.isoformat())
    db_session.refresh(job)
    assert job.scheduled_for.replace(tzinfo=timezone.utc) == when
    assert out["scheduled_for"].startswith("2026-09-12T18:00:00")


def test_update_account_hold_for_review_youtube_ok(db_session, make_account):
    from app.assistant.tools import update_account
    from app.db.models import Platform

    account = make_account(username="ythold", platform=Platform.youtube)
    out = update_account(db_session, account.id, hold_for_review=True, daily_post_cap=5)
    assert out["hold_for_review"] is True
    assert out["daily_post_cap"] == 5
    db_session.refresh(account)
    assert account.hold_for_review is True
    assert account.daily_post_cap == 5


def test_plan_account_duration_and_auto_schedule(db_session, make_account):
    from app.assistant.tools import plan_account

    account = make_account()
    out = plan_account(db_session, account.id, count=2, duration_s=8, auto_schedule=False)
    job = db_session.get(PlanJob, out["queued_plan_id"])
    assert job is not None
    assert job.duration_s == 8.0
    assert job.auto_schedule is False


def test_describe_covers_factory_tools():
    from app.assistant.chat import describe

    assert describe("create_render", {"prompt": "fog"}) == "ставлю рендер"
    assert describe("list_render_backends", {}) == "смотрю движки рендера"
    assert describe("compose", {"clip_ids": [1, 2]}) == "ставлю склейку"
    assert describe("reschedule_job", {"job_id": 1}) == "переношу слот"
    assert describe("list_questions", {}) == "смотрю вопросы агента"
    assert describe("apply_preset", {"account_id": 1, "name": "x"}) == "ставлю пресет"


def test_open_page_accepts_query():
    opened = open_page("activity?status=dead")
    assert opened.path == "/activity"
    assert opened.query == {"status": "dead"}
    assert opened.as_url() == "/activity?status=dead"
    opened = open_page("accounts?username=alice")
    assert opened.path == "/accounts"
    assert opened.query == {"username": "alice"}
    opened = open_page("активность?status=dead")
    assert opened.path == "/activity"
    assert opened.query == {"status": "dead"}


def test_overview_badges(db_session, make_account):
    from app.assistant.tools import overview
    from app.db.models import Clarification, question_key

    account = make_account()
    now = datetime.now(timezone.utc)
    db_session.add(
        PostJob(
            account_id=account.id,
            source_video_path="/a.mp4",
            scheduled_for=now,
            status=PostJobStatus.awaiting_review,
        )
    )
    db_session.add(
        PostJob(
            account_id=account.id,
            source_video_path="/b.mp4",
            scheduled_for=now,
            status=PostJobStatus.dead,
            finished_at=now,
        )
    )
    db_session.add(
        Clarification(
            account_id=account.id,
            question="для кого это?",
            question_key=question_key("для кого это?"),
        )
    )
    db_session.commit()
    body = overview(db_session)
    assert body["jobs_awaiting_review"] == 1
    assert body["open_questions"] == 1
    assert body["errors_24h"] == 1


def test_list_questions_sources_presets_plans(db_session, make_account):
    from app.assistant.tools import (
        add_source,
        apply_preset,
        list_plans,
        list_presets,
        list_questions,
        list_sources,
        plan_account,
    )
    from app.db.models import Clarification, question_key

    account = make_account()
    db_session.add(
        Clarification(
            account_id=account.id,
            question="какой тон?",
            question_key=question_key("какой тон?"),
            why="бриф молчит",
        )
    )
    db_session.commit()
    qs = list_questions(db_session, account_id=account.id)
    assert qs and qs[0]["question"] == "какой тон?"
    assert qs[0]["open"] is True

    add_source(db_session, account.id, "https://example.com/feed")
    srcs = list_sources(db_session, account.id)
    assert srcs and srcs[0]["value"] == "https://example.com/feed"

    presets = list_presets(db_session)
    assert any(p["name"] == "Calm nature" for p in presets)
    applied = apply_preset(db_session, account.id, "Calm nature")
    assert "Misty forests" in applied["brief"]

    plan_account(db_session, account.id, count=2, week=True)
    plans = list_plans(db_session, account_id=account.id)
    assert plans and plans[0]["week"] is True
    assert plans[0]["count"] == 2


def test_account_details_includes_cooldown(db_session, make_account):
    from app.assistant.tools import account_details

    account = make_account()
    account.cooldown_until = datetime.now(timezone.utc)
    db_session.commit()
    details = account_details(db_session, account.id)
    assert details["cooldown_until"]


def test_test_proxy_reports_geo_mismatch(db_session, make_proxy, monkeypatch):
    from datetime import datetime, timezone

    from app.assistant.tools import test_proxy
    from app.proxies.pool import HealthSnapshot

    make_proxy(label="geo-de", country="US")

    def fake_health(_db, row):
        snap = HealthSnapshot(
            ok=True,
            ip="1.1.1.1",
            country="DE",
            instagram_reachable=True,
            instagram_login_reachable=True,
            checked_at=datetime.now(timezone.utc),
        )
        return True, snap, None

    monkeypatch.setattr("app.proxies.pool.health_check_record", fake_health)
    out = test_proxy(db_session, "geo-de")
    assert out["geo_mismatch"] is True
    assert out["advertised_country"] == "US"
    assert out["actual_country"] == "DE"


def test_plan_account_warns_when_worker_is_down(db_session, make_account):
    account = make_account()
    out = plan_account(db_session, account.id, week=True)
    assert out["queued_plan_id"]
    assert out.get("предупреждение") == "воркер стоит, план в очереди"



