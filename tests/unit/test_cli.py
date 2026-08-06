"""Tests for app.cli (Typer CLI)."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx
from sqlalchemy import select
from typer.testing import CliRunner

from app.config import settings
from app.db import (
    Account,
    AccountStatus,
    PostJob,
    PostJobStatus,
    Proxy,
)
from app import cli as cli_module


runner = CliRunner()


@pytest.fixture()
def cli_app(app_env):
    """Initialize the schema once. ``app_env`` patches DB module references."""
    return cli_module.app


def test_init_db(cli_app):
    result = runner.invoke(cli_app, ["init-db"])
    assert result.exit_code == 0


def test_import_proxies_from_json(cli_app, db_session, tmp_path):
    path = tmp_path / "proxies.json"
    path.write_text(
        '[{"label":"imp-1","url":"http://a:b@c:443","country":"US","timezone":"UTC","notes":"x"}]',
        encoding="utf-8",
    )
    result = runner.invoke(
        cli_app,
        ["import-proxies", str(path), "--skip-health-check"],
    )
    assert result.exit_code == 0, result.stdout
    proxy = db_session.scalar(select(Proxy).where(Proxy.label == "imp-1"))
    assert proxy is not None
    assert proxy.url == "http://a:b@c:443"
    assert proxy.country == "US"
    assert proxy.timezone == "UTC"
    assert proxy.notes == "x"


@respx.mock
def test_add_proxy_with_health_check_ok(cli_app, db_session):
    from app.proxies.pool import reset_health_cache

    reset_health_cache()
    respx.get(settings.proxy_health_url).mock(
        return_value=httpx.Response(200, json={"ip": "9.9.9.9"})
    )
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        return_value=httpx.Response(200, text="{}")
    )
    respx.get("https://www.instagram.com/accounts/login/").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    respx.get("https://ipapi.co/json/").mock(
        return_value=httpx.Response(
            200, json={"country_code": "US", "timezone": "America/New_York"}
        )
    )
    result = runner.invoke(
        cli_app,
        ["add-proxy", "--label", "p1", "--url", "http://u:p@h:1", "--country", "US"],
    )
    assert result.exit_code == 0, result.stdout
    proxy = db_session.scalar(select(Proxy).where(Proxy.label == "p1"))
    assert proxy is not None
    assert proxy.last_known_ip == "9.9.9.9"


@respx.mock
def test_add_proxy_health_check_failure_exits_1(cli_app, db_session):
    from app.proxies.pool import reset_health_cache

    reset_health_cache()
    respx.get(settings.proxy_health_url).mock(return_value=httpx.Response(500))
    result = runner.invoke(
        cli_app,
        ["add-proxy", "--label", "px", "--url", "http://h:1"],
    )
    assert result.exit_code == 1


def test_add_proxy_skip_health_check(cli_app, db_session):
    result = runner.invoke(
        cli_app,
        ["add-proxy", "--label", "p2", "--url", "http://h:2", "--skip-health-check"],
    )
    assert result.exit_code == 0
    assert db_session.scalar(select(Proxy).where(Proxy.label == "p2")) is not None


def test_add_account_utc_default_uses_proxy_timezone(cli_app, db_session, make_proxy):
    make_proxy(label="p-pl", url="http://h:pl", country="PL", timezone="Europe/Warsaw")
    result = runner.invoke(
        cli_app,
        [
            "add-account",
            "--username", "pluser",
            "--password", "pwd",
            "--proxy", "p-pl",
        ],
    )
    assert result.exit_code == 0, result.stdout
    account = db_session.scalar(select(Account).where(Account.username == "pluser"))
    assert account is not None
    assert account.timezone == "Europe/Warsaw"


def test_add_account_links_proxy(cli_app, db_session, make_proxy):
    proxy = make_proxy(label="p3", url="http://h:3", country="DE")
    result = runner.invoke(
        cli_app,
        [
            "add-account",
            "--username", "alice",
            "--password", "pwd",
            "--proxy", "p3",
            "--timezone", "Europe/Berlin",
        ],
    )
    assert result.exit_code == 0, result.stdout
    account = db_session.scalar(select(Account).where(Account.username == "alice"))
    assert account is not None
    assert account.proxy_id == proxy.id
    assert account.timezone == "Europe/Berlin"


def test_add_account_unknown_proxy_fails(cli_app):
    result = runner.invoke(
        cli_app,
        [
            "add-account",
            "--username", "bob",
            "--password", "pwd",
            "--proxy", "missing",
        ],
    )
    assert result.exit_code == 1


def test_add_account_updates_existing(cli_app, db_session, make_proxy):
    make_proxy(label="p4", url="http://h:4")
    runner.invoke(
        cli_app,
        ["add-account", "--username", "carol", "--password", "p1", "--proxy", "p4"],
    )
    res2 = runner.invoke(
        cli_app,
        ["add-account", "--username", "carol", "--password", "p2", "--proxy", "p4",
         "--daily-post-cap", "5"],
    )
    assert res2.exit_code == 0
    account = db_session.scalar(select(Account).where(Account.username == "carol"))
    assert account.password == "p2"
    assert account.daily_post_cap == 5


def test_enqueue_post_creates_job(cli_app, db_session, make_account, app_env):
    account = make_account(username="dave")
    video = app_env.video_source_dir / "v.mp4"
    video.write_bytes(b"x")

    result = runner.invoke(
        cli_app,
        ["enqueue-post", "--username", "dave", "--video", str(video)],
    )
    assert result.exit_code == 0, result.stdout
    job = db_session.scalar(select(PostJob).where(PostJob.account_id == account.id))
    assert job is not None
    assert job.status == PostJobStatus.queued


def test_enqueue_post_unknown_account_fails(cli_app, app_env):
    video = app_env.video_source_dir / "v.mp4"
    video.write_bytes(b"x")
    result = runner.invoke(
        cli_app,
        ["enqueue-post", "--username", "ghost", "--video", str(video)],
    )
    assert result.exit_code == 1


def test_enqueue_post_with_explicit_when(cli_app, db_session, make_account, app_env):
    make_account(username="eric")
    video = app_env.video_source_dir / "v.mp4"
    video.write_bytes(b"x")
    when = "2030-01-01T12:00:00"
    result = runner.invoke(
        cli_app,
        ["enqueue-post", "--username", "eric", "--video", str(video), "--when", when],
    )
    assert result.exit_code == 0
    job = db_session.scalar(select(PostJob).where(PostJob.source_video_path == str(video)))
    assert job.scheduled_for.year == 2030


def test_plan_week_creates_jobs(cli_app, db_session, make_account, app_env, monkeypatch):
    import app.scheduler.planner as planner_module

    monkeypatch.setattr(planner_module, "DAILY_SKIP_PROB", 0.0, raising=True)
    make_account(username="frank", daily_post_cap=2)
    src_dir = app_env.video_source_dir
    (src_dir / "v1.mp4").write_bytes(b"x")
    (src_dir / "v2.mp4").write_bytes(b"x")

    result = runner.invoke(
        cli_app,
        ["plan-week", "--username", "frank", "--days", "2", "--sources-dir", str(src_dir)],
    )
    assert result.exit_code == 0
    jobs = db_session.scalars(select(PostJob)).all()
    assert len(jobs) >= 1


def test_plan_week_no_videos_fails(cli_app, app_env, make_account):
    make_account(username="gina")
    src_dir = app_env.tmp_path / "empty"
    src_dir.mkdir()
    result = runner.invoke(
        cli_app,
        ["plan-week", "--username", "gina", "--sources-dir", str(src_dir)],
    )
    assert result.exit_code == 1


def test_pause_and_resume_account(cli_app, db_session, make_account):
    make_account(username="hank")
    res_pause = runner.invoke(cli_app, ["pause-account", "hank"])
    assert res_pause.exit_code == 0
    db_session.expire_all()
    account = db_session.scalar(select(Account).where(Account.username == "hank"))
    assert account.status == AccountStatus.paused

    res_resume = runner.invoke(cli_app, ["resume-account", "hank"])
    assert res_resume.exit_code == 0
    db_session.expire_all()
    account = db_session.scalar(select(Account).where(Account.username == "hank"))
    assert account.status == AccountStatus.active


def test_pause_unknown_account_fails(cli_app):
    result = runner.invoke(cli_app, ["pause-account", "nobody"])
    assert result.exit_code == 1


def test_rotate_proxy(cli_app, db_session, make_account, make_proxy):
    make_account(username="ivy")
    new_proxy = make_proxy(label="alt", url="http://h:9", country="GB")
    result = runner.invoke(cli_app, ["rotate-proxy", "ivy", "alt"])
    assert result.exit_code == 0
    account = db_session.scalar(select(Account).where(Account.username == "ivy"))
    assert account.proxy_id == new_proxy.id


def test_rotate_proxy_unknown_target_fails(cli_app, make_account):
    make_account(username="jack")
    result = runner.invoke(cli_app, ["rotate-proxy", "jack", "nope"])
    assert result.exit_code == 1


def test_provide_code_writes_file_and_resets_status(cli_app, db_session, make_account, app_env):
    make_account(username="kate", status=AccountStatus.challenge)
    result = runner.invoke(cli_app, ["provide-code", "kate", "112233"])
    assert result.exit_code == 0
    code_file = app_env.challenges_dir / "kate.code"
    assert code_file.exists()
    assert code_file.read_text(encoding="utf-8") == "112233"
    db_session.expire_all()
    acc = db_session.scalar(select(Account).where(Account.username == "kate"))
    assert acc.status == AccountStatus.active


def test_list_accounts(cli_app, make_account):
    make_account(username="liz")
    make_account(username="mike", proxy=None)  # uses default factory's new proxy
    result = runner.invoke(cli_app, ["list-accounts"])
    assert result.exit_code == 0
    assert "liz" in result.stdout
    assert "mike" in result.stdout


def test_status_command(cli_app, make_account, db_session):
    account = make_account(username="nora")
    db_session.add(
        PostJob(
            account_id=account.id,
            source_video_path="v.mp4",
            scheduled_for=datetime.now(timezone.utc),
            status=PostJobStatus.queued,
        )
    )
    db_session.commit()
    result = runner.invoke(cli_app, ["status"])
    assert result.exit_code == 0


def test_export_account_returns_fingerprint(cli_app, make_account):
    make_account(username="oscar")
    # Create a fingerprint by invoking ensure indirectly via add-account?
    # The factory is invoked in add-account command flow; here we just call the
    # device_factory directly to seed.
    from app.accounts.session_manager import ensure_fingerprint_and_proxy

    ensure_fingerprint_and_proxy("oscar", country="US")
    result = runner.invoke(cli_app, ["export-account", "oscar"])
    assert result.exit_code == 0
    assert "user_agent" in result.stdout


def test_export_account_missing_fails(cli_app):
    result = runner.invoke(cli_app, ["export-account", "ghostuser"])
    assert result.exit_code == 1


def test_run_worker_invokes_run(cli_app, monkeypatch):
    called = {"n": 0}

    def _fake_run():
        called["n"] += 1

    import app.scheduler.worker as worker_module

    monkeypatch.setattr(worker_module, "run", _fake_run)
    result = runner.invoke(cli_app, ["run-worker"])
    assert result.exit_code == 0
    assert called["n"] == 1


def test_install_playwright_invokes_subprocess(cli_app, monkeypatch):
    called = {"cmd": None}

    def _fake_run(cmd, check):
        called["cmd"] = cmd
        assert check is True
        return 0

    monkeypatch.setattr("app.cli.subprocess.run", _fake_run)
    result = runner.invoke(cli_app, ["install-playwright", "--browser", "chromium"])
    assert result.exit_code == 0
    assert called["cmd"] is not None
    assert called["cmd"][-2:] == ["install", "chromium"]
