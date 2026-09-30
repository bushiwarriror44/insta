"""Operations CLI.

Examples
--------
Initialize the database::

    python -m app.cli init-db

Import proxies from a JSON array (alternative to UI / ``add-proxy``)::

    python -m app.cli import-proxies ./examples/local-proxies.seed.json --skip-health-check

Add a proxy and an account, optionally with a first stealth Playwright login::

    python -m app.cli add-proxy --label res-de-1 --url http://u:p@host:8000 --country DE --timezone Europe/Berlin
    python -m app.cli add-account --username name --password pwd --proxy res-de-1 --timezone Europe/Berlin
    python -m app.cli first-login name

Enqueue a single video and run the worker::

    python -m app.cli enqueue-post --username name --video data/videos/source/clip.mp4
    python -m app.cli run-worker

    python -m app.cli ask "создай прокси и аккаунт, войди, опубликуй clip.mp4"

Inspect state::

    python -m app.cli status
    python -m app.cli list-accounts
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from app.accounts.challenge import write_code
from app.accounts.session_manager import clear_session_file, ensure_fingerprint_and_proxy
from app.config import settings
from app.geo.timezone_normalize import (
    is_placeholder_timezone,
    normalize_playwright_timezone,
    timezone_from_proxy,
)
from app.db import (
    Account,
    AccountStatus,
    DailyStat,
    Platform,
    PostJob,
    PostJobStatus,
    Proxy,
    SessionLocal,
    init_db as _init_db,
)
from app.logging_setup import configure_logging, get_logger
from app.proxies.pool import health_check_record, upsert_proxy
from app.scheduler.planner import schedule_jobs
from app.services.review import initial_job_status

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Instagram Reels publisher CLI")
console = Console()
logger = get_logger(__name__)


def _bootstrap() -> None:
    configure_logging()
    _init_db()


@app.command("init-db")
def cmd_init_db() -> None:
    """Create the SQLite schema."""
    _bootstrap()
    console.print("[green]Database initialized at[/green]", settings.database_url)


@app.command("import-proxies")
def cmd_import_proxies(
    path: Path = typer.Argument(..., help="JSON file: list of proxy objects"),
    skip_health_check: bool = typer.Option(
        False,
        "--skip-health-check",
        help="Register proxies without running health-check",
    ),
) -> None:
    """Upsert proxies from a JSON file (admin UI/API is preferred for day-to-day).

    Expected format::

        [{"label": "mob-1", "url": "http://u:p@host:443", "country": "US", ...}, ...]

    """
    _bootstrap()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print("[red]Invalid JSON[/red]", exc)
        raise typer.Exit(code=1)
    if not isinstance(data, list):
        console.print("[red]Root JSON value must be a list[/red]")
        raise typer.Exit(code=1)

    failures = False
    with SessionLocal() as db:
        for i, raw in enumerate(data):
            if not isinstance(raw, dict):
                console.print(f"[yellow]Skipping item {i}: not an object[/yellow]")
                continue
            label = str(raw.get("label", "")).strip()
            url = str(raw.get("url", "")).strip()
            if not label or not url:
                console.print(f"[yellow]Skipping item {i}: missing label or url[/yellow]")
                continue
            co = raw.get("country")
            tz = raw.get("timezone") or raw.get("timezone_name")
            nt = raw.get("notes")
            country_s = str(co).strip() if co is not None else None
            if country_s == "":
                country_s = None
            timezone_s = str(tz).strip() if tz is not None else None
            if timezone_s == "":
                timezone_s = None
            notes_s = str(nt).strip() if nt is not None else None
            if notes_s == "":
                notes_s = None
            proxy = upsert_proxy(
                db,
                label=label,
                url=url,
                country=country_s,
                timezone_name=timezone_s,
                notes=notes_s,
            )
            if skip_health_check:
                console.print(f"[green]{label}[/green] upserted")
            elif not health_check_record(db, proxy)[0]:
                console.print(f"[yellow]{label} upserted but health-check failed[/yellow]")
                failures = True
            else:
                console.print(f"[green]{label}[/green] ready ip={proxy.last_known_ip or '?'}")
    if failures:
        raise typer.Exit(code=1)


@app.command("add-proxy")
def cmd_add_proxy(
    label: str = typer.Option(..., "--label", help="Unique label for the proxy"),
    url: str = typer.Option(..., "--url", help="http(s)://user:pass@host:port"),
    country: Optional[str] = typer.Option(None, "--country", help="2-letter country code"),
    timezone_name: Optional[str] = typer.Option(None, "--timezone", help="IANA timezone, e.g. Europe/Berlin"),
    notes: Optional[str] = typer.Option(None, "--notes"),
    skip_health_check: bool = typer.Option(False, "--skip-health-check"),
) -> None:
    """Register or update a proxy entry."""
    _bootstrap()
    with SessionLocal() as db:
        proxy = upsert_proxy(db, label=label, url=url, country=country, timezone_name=timezone_name, notes=notes)
        if not skip_health_check:
            ok, _snapshot, _err = health_check_record(db, proxy)
            if not ok:
                console.print(f"[yellow]Proxy {label} is registered but failed health-check.[/yellow]")
                raise typer.Exit(code=1)
        console.print(f"[green]Proxy {label} ready[/green] ip={proxy.last_known_ip or '?'} country={proxy.country or '?'}")


@app.command("add-account")
def cmd_add_account(
    username: str = typer.Option(..., "--username"),
    password: str = typer.Option(..., "--password", prompt=True, hide_input=True),
    proxy_label: str = typer.Option(..., "--proxy", help="Label of an existing proxy"),
    email: Optional[str] = typer.Option(None, "--email"),
    email_password: Optional[str] = typer.Option(None, "--email-password"),
    totp_seed: Optional[str] = typer.Option(None, "--totp-seed"),
    session_id: Optional[str] = typer.Option(None, "--session-id"),
    timezone_name: str = typer.Option("UTC", "--timezone"),
    daily_post_cap: int = typer.Option(settings.default_daily_post_cap, "--daily-post-cap"),
    min_gap_hours: float = typer.Option(settings.default_min_gap_hours, "--min-gap-hours"),
    active_hour_start: int = typer.Option(settings.default_active_hour_start, "--active-hour-start"),
    active_hour_end: int = typer.Option(settings.default_active_hour_end, "--active-hour-end"),
    platform: str = typer.Option(
        "instagram",
        "--platform",
        help="instagram, youtube, or tiktok",
    ),
) -> None:
    """Register an account and bind it to a proxy."""
    _bootstrap()
    try:
        platform_enum = Platform(platform.strip().lower())
    except ValueError:
        console.print(f"[red]Unknown platform {platform!r}[/red]")
        raise typer.Exit(code=1)
    with SessionLocal() as db:
        proxy = db.scalar(select(Proxy).where(Proxy.label == proxy_label))
        if proxy is None:
            console.print(f"[red]Proxy {proxy_label} not found. Add it first.[/red]")
            raise typer.Exit(code=1)

        existing = db.scalar(
            select(Account).where(
                Account.username == username,
                Account.platform == platform_enum,
            )
        )
        if existing is not None:
            console.print(
                f"[yellow]Account {username} ({platform_enum.value}) already exists. Updating fields.[/yellow]"
            )
            account = existing
        else:
            account = Account(username=username, platform=platform_enum)
            db.add(account)

        account.platform = platform_enum
        account.password = password
        account.email = email
        account.email_password = email_password
        account.totp_seed = totp_seed
        if session_id is not None:
            account.session_id = session_id.strip() or None
            if account.session_id:
                clear_session_file(account.username)
        account.proxy_id = proxy.id
        if is_placeholder_timezone(timezone_name):
            account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
        else:
            account.timezone = normalize_playwright_timezone(timezone_name, country=proxy.country)
        account.daily_post_cap = daily_post_cap
        account.min_gap_hours = min_gap_hours
        account.active_hour_start = active_hour_start
        account.active_hour_end = active_hour_end
        if account.status == AccountStatus.blocked:
            account.status = AccountStatus.active
        db.commit()
        db.refresh(account)

        fp = ensure_fingerprint_and_proxy(
            account.username,
            country=proxy.country or "US",
            timezone_id=account.timezone,
        )
        console.print(
            f"[green]Account {username} ready[/green] "
            f"device={fp.settings['device_settings']['model']} country={fp.country} locale={fp.locale}"
        )


@app.command("refresh-app-versions")
def cmd_refresh_app_versions(
    file: Path = typer.Option(
        Path("data/app_versions.json"),
        "--file",
        help="Path to a JSON list of {version, code} entries.",
    ),
) -> None:
    """Reload the Instagram Android app version pool from a local JSON file.

    Format::

        [
            {"version": "448.0.0.0.20", "code": "1065560286"},
            {"version": "446.0.0.49.77", "code": "385211303"}
        ]
    """
    _bootstrap()
    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(code=1)
    from app.accounts.device_factory import (
        load_app_versions_from_file,
        set_app_versions,
    )
    try:
        values = load_app_versions_from_file(file)
    except (ValueError, json.JSONDecodeError) as exc:
        console.print(f"[red]Failed to load: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    set_app_versions(values)
    console.print(
        f"[green]Loaded {len(values)} Instagram app versions[/green] from {file} "
        f"(latest: {values[-1][0]})"
    )


@app.command("install-playwright")
def cmd_install_playwright(
    browser: str = typer.Option("chromium", "--browser", help="Playwright browser to install."),
) -> None:
    """Install Playwright browser binaries on demand."""
    _bootstrap()
    console.print(f"[cyan]Installing Playwright browser:[/cyan] {browser}")
    try:
        subprocess.run(
            [str(Path(sys.executable)), "-m", "playwright", "install", browser],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Playwright install failed[/red] (exit={exc.returncode})")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Playwright browser installed:[/green] {browser}")


@app.command("first-login")
def cmd_first_login(username: str) -> None:
    """Perform a stealth Playwright first login. Use for fresh accounts."""
    _bootstrap()
    from app.accounts.first_login_service import run_account_first_login

    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            console.print(f"[red]Account {username} not found[/red]")
            raise typer.Exit(code=1)
        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        if proxy is None:
            console.print(f"[red]Account {username} has no proxy assigned. First-login is blocked.[/red]")
            raise typer.Exit(code=1)
        out = run_account_first_login(account, db)
        if out.ok:
            console.print(f"[green]First login flow completed for {username}[/green]")
            return
        console.print(
            f"[yellow]First login finished with warnings for {username}. "
            f"{out.error or 'Check logs.'}[/yellow]"
        )
        raise typer.Exit(code=1)


@app.command("enqueue-post")
def cmd_enqueue(
    username: str = typer.Option(..., "--username"),
    video: Path = typer.Option(..., "--video", exists=True, file_okay=True, dir_okay=False, readable=True),
    caption_template: Optional[str] = typer.Option(None, "--caption-template"),
    when: Optional[str] = typer.Option(None, "--when", help="ISO datetime in UTC; default: now + random 1-30 min"),
) -> None:
    """Enqueue a single video for the given account."""
    _bootstrap()
    from app.services.media import MediaError, resolve_library_media_path

    try:
        src = resolve_library_media_path(video, settings.video_source_dir)
    except MediaError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            console.print(f"[red]Account {username} not found[/red]")
            raise typer.Exit(code=1)
        if when:
            scheduled_for = datetime.fromisoformat(when)
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        else:
            import random as _r

            scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=_r.randint(1, 30))
        job = PostJob(
            account_id=account.id,
            source_video_path=str(src),
            caption_template=caption_template,
            scheduled_for=scheduled_for,
            status=initial_job_status(account),
        )
        db.add(job)
        db.commit()
        console.print(f"[green]Enqueued job[/green] id={job.id} username={username} at {scheduled_for.isoformat()}")


@app.command("plan-week")
def cmd_plan_week(
    username: str = typer.Option(..., "--username"),
    days: int = typer.Option(7, "--days", min=1, max=14),
    sources_dir: Path = typer.Option(settings.video_source_dir, "--sources-dir", exists=True, file_okay=False),
    caption_template: Optional[str] = typer.Option(None, "--caption-template"),
) -> None:
    """Auto-generate a per-account schedule from videos in ``sources_dir``."""
    _bootstrap()
    videos = sorted(p for p in sources_dir.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".m4v"})
    if not videos:
        console.print(f"[red]No videos found in {sources_dir}[/red]")
        raise typer.Exit(code=1)
    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            console.print(f"[red]Account {username} not found[/red]")
            raise typer.Exit(code=1)
        created = schedule_jobs(
            db,
            account,
            sources=[str(v.resolve()) for v in videos],
            caption_template=caption_template,
            days_ahead=days,
        )
        console.print(f"[green]Scheduled {len(created)} jobs[/green] over {days} day(s)")


@app.command("run-worker")
def cmd_run_worker() -> None:
    """Start the polling worker (foreground process)."""
    _bootstrap()
    from app.scheduler.worker import run

    run()


@app.command("run-api")
def cmd_run_api(
    host: str = typer.Option(settings.api_host, "--host"),
    port: int = typer.Option(settings.api_port, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Enable autoreload (dev only)"),
) -> None:
    """Start the FastAPI admin server (foreground process)."""
    _bootstrap()
    import uvicorn

    console.print(
        f"[green]Starting admin API[/green] on http://{host}:{port} "
        f"(auth_required={'yes' if settings.admin_token else 'no'})"
    )
    uvicorn.run(
        "app.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command("ask")
def cmd_ask(prompt: str = typer.Argument(..., help="Text instruction for the local LLM")) -> None:
    """Send one prompt to the local LLM with browser tools (same as POST /api/assistant/run)."""
    _bootstrap()
    from app.assistant.chat import AssistantError, ask

    with SessionLocal() as db:
        try:
            answer = ask(
                db,
                [{"role": "user", "content": prompt}],
                allow_browser=True,
                viewer_role="owner",
            )
        except AssistantError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
    console.print(answer.reply)
    if answer.asks:
        for question in answer.asks:
            console.print(f"  ? {question}")
    if answer.used:
        console.print("[dim]used[/dim]", ", ".join(answer.used))


@app.command("provide-code")
def cmd_provide_code(username: str, code: str) -> None:
    """Drop a challenge code for an account that's currently waiting."""
    _bootstrap()
    write_code(username, code)
    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is not None and account.status == AccountStatus.challenge:
            account.status = AccountStatus.active
            db.commit()
    console.print(f"[green]Code recorded for {username}[/green]")


@app.command("pause-account")
def cmd_pause(username: str) -> None:
    _bootstrap()
    _set_status(username, AccountStatus.paused)


@app.command("resume-account")
def cmd_resume(username: str) -> None:
    _bootstrap()
    _set_status(username, AccountStatus.active)


@app.command("rotate-proxy")
def cmd_rotate_proxy(username: str, proxy_label: str) -> None:
    """Rebind an account to a different proxy. WARNING: changes IP for this account."""
    _bootstrap()
    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.username == username))
        proxy = db.scalar(select(Proxy).where(Proxy.label == proxy_label))
        if account is None or proxy is None:
            console.print("[red]Account or proxy not found[/red]")
            raise typer.Exit(code=1)
        account.proxy_id = proxy.id
        db.commit()
        console.print(f"[green]Account {username} now uses proxy {proxy_label}[/green]")


@app.command("list-accounts")
def cmd_list_accounts() -> None:
    _bootstrap()
    with SessionLocal() as db:
        accounts = db.scalars(select(Account).order_by(Account.username)).all()
        table = Table(title="Accounts")
        table.add_column("Username")
        table.add_column("Status")
        table.add_column("Proxy")
        table.add_column("TZ")
        table.add_column("Cap")
        table.add_column("Last publish")
        for a in accounts:
            proxy = db.get(Proxy, a.proxy_id) if a.proxy_id else None
            table.add_row(
                a.username,
                a.status.value,
                proxy.label if proxy else "-",
                a.timezone,
                str(a.daily_post_cap),
                a.last_publish_at.isoformat() if a.last_publish_at else "-",
            )
        console.print(table)


@app.command("status")
def cmd_status(
    show_entry_path: bool = typer.Option(
        False,
        "--show-entry-path",
        help="Print the panel secret URL path (sensitive; default is hidden).",
    ),
) -> None:
    """Quick health snapshot: jobs in flight, recent errors, daily stats."""
    _bootstrap()
    today = datetime.now(timezone.utc).date().isoformat()
    with SessionLocal() as db:
        from app.panel.settings_store import get_or_create_panel_settings

        panel = get_or_create_panel_settings(db)
        if show_entry_path:
            console.print(f"[bold]Panel entry path:[/bold] {panel.entry_path}")
        queued = db.scalar(select(PostJob).where(PostJob.status == PostJobStatus.queued).order_by(PostJob.scheduled_for).limit(1))
        running = db.scalars(select(PostJob).where(PostJob.status == PostJobStatus.running)).all()
        dead = db.scalars(
            select(PostJob).where(PostJob.status == PostJobStatus.dead).order_by(PostJob.finished_at.desc()).limit(5)
        ).all()
        stats = db.scalars(select(DailyStat).where(DailyStat.date_key == today)).all()
        console.print(f"[bold]Today ({today})[/bold]")
        for s in stats:
            account = db.get(Account, s.account_id)
            uname = account.username if account else f"#{s.account_id}"
            console.print(f"  @{uname}: posts={s.posts_count} fails={s.failures_count}")
        console.print(f"\n[bold]Running:[/bold] {len(running)} job(s)")
        if queued is not None:
            console.print(f"[bold]Next queued:[/bold] job {queued.id} at {queued.scheduled_for.isoformat()}")
        if dead:
            console.print("[bold]Recent dead jobs:[/bold]")
            for d in dead:
                console.print(f"  job {d.id} (account {d.account_id}): {d.last_error}")


@app.command("preflight")
def cmd_preflight() -> None:
    """Run lightweight operational checks before worker start."""
    _bootstrap()
    issues: list[str] = []
    if not settings.data_dir.exists():
        issues.append("data_dir missing")
    if not settings.sessions_dir.exists():
        issues.append("sessions_dir missing")
    from app.behavior.warmup_playwright import playwright_browsers_available

    if not playwright_browsers_available():
        issues.append("playwright browser cache is empty (run install-playwright)")

    import shutil

    if shutil.which("ffmpeg") is None:
        issues.append("ffmpeg missing (slideshow/uniquify)")

    with SessionLocal() as db:
        proxies = db.scalars(select(Proxy)).all()
        if not proxies:
            issues.append("no proxies configured")
        unhealthy = [p.label for p in proxies if not p.is_healthy]
        if unhealthy:
            issues.append(f"unhealthy proxies: {', '.join(unhealthy[:5])}")

    if issues:
        for item in issues:
            console.print(f"[yellow]preflight:[/yellow] {item}")
        raise typer.Exit(code=1)
    console.print("[green]preflight ok[/green]")


@app.command("browser-vnc-diag")
def cmd_browser_vnc_diag(
    username: Optional[str] = typer.Argument(
        None,
        help="Optional account username to print browser/status curl example",
    ),
) -> None:
    """Run noVNC / WebSocket troubleshooting checks (execute on the VPS)."""
    _bootstrap()
    from app.browser.session_manager import browser_session_manager
    from app.browser.vnc_stack import vnc_stack_available
    from app.behavior.warmup_playwright import playwright_browsers_available

    import os

    console.print("[bold]noVNC / browser diagnostics[/bold]")
    console.print(f"  BROWSER_VNC_ENABLED={settings.browser_vnc_enabled}")
    console.print(f"  DISPLAY={os.environ.get('DISPLAY', ':99')}")

    tools = {
        "Xvfb": shutil_which("Xvfb"),
        "x11vnc": shutil_which("x11vnc"),
        "websockify": shutil_which("websockify"),
    }
    for name, path in tools.items():
        status = f"[green]{path}[/green]" if path else "[red]missing[/red]"
        console.print(f"  {name}: {status}")

    console.print(f"  vnc_stack_available={vnc_stack_available()}")
    console.print(f"  playwright_browsers_available={playwright_browsers_available()}")
    console.print(f"  novnc_static={'yes' if Path('/usr/share/novnc').is_dir() else 'no'}")

    if username:
        data = browser_session_manager.status_dict(username)
        console.print(f"\n[bold]Session @{username}[/bold]")
        console.print_json(json.dumps(data))
        token_hint = "YOUR_ADMIN_TOKEN" if settings.admin_token else "(auth disabled)"
        console.print("\n[dim]HTTP status (from host):[/dim]")
        console.print(
            f'  curl -s -H "Authorization: Bearer {token_hint}" '
            f"http://127.0.0.1:8000/api/accounts/{username}/browser/status"
        )
        console.print("\n[dim]WebSocket (query token, no Bearer header):[/dim]")
        console.print(
            f'  wscat -c "ws://127.0.0.1:8000/api/accounts/{username}/browser/vnc/ws?token={token_hint}"'
        )
        console.print("\n[dim]Through frontend nginx:[/dim]")
        console.print(
            f'  wscat -c "ws://127.0.0.1:3000/api/accounts/{username}/browser/vnc/ws?token={token_hint}"'
        )

    console.print("\n[dim]Host checks:[/dim]")
    console.print("  docker compose ps")
    console.print("  ss -tlnp | grep -E ':80|:3000|:8000'")
    console.print("  docker compose logs -f reels-api --tail=50")
    console.print("\n[yellow]If port 80 is host nginx -> :3000 (not docker directly):[/yellow]")
    console.print("  outer nginx MUST forward WebSocket Upgrade headers.")
    console.print("  See deploy/host-nginx.conf.example — copy to /etc/nginx/sites-available/insta")
    console.print("  sudo nginx -t && sudo systemctl reload nginx")


def shutil_which(cmd: str) -> str | None:
    import shutil

    return shutil.which(cmd)


@app.command("export-account")
def cmd_export_account(username: str) -> None:
    """Dump the persisted device fingerprint for backup/migration."""
    _bootstrap()
    from app.accounts.device_factory import load_fingerprint

    fp = load_fingerprint(username)
    if fp is None:
        console.print(f"[red]No fingerprint found for {username}[/red]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(fp.to_dict()))


def _set_status(username: str, status: AccountStatus) -> None:
    with SessionLocal() as db:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            console.print(f"[red]Account {username} not found[/red]")
            raise typer.Exit(code=1)
        account.status = status
        db.commit()
        console.print(f"[green]Account {username} -> {status.value}[/green]")


if __name__ == "__main__":
    app()
