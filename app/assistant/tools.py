"""Panel assistant tools: read everything (including secrets), create/update accounts and proxies.

Never delete.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import re
import socket
import subprocess
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Account,
    AccountStatus,
    AssetKind,
    ChannelSource,
    Clarification,
    Composition,
    CompositionClip,
    DiagnosticRun,
    DiagnosticRunKind,
    DiagnosticRunStatus,
    Event,
    EventLevel,
    GenerationJob,
    MediaAsset,
    PanelOperator,
    PipelineStatus,
    PlanJob,
    Platform,
    PostJob,
    PostJobStatus,
    PostLog,
    PostType,
    PromptPreset,
    Proxy,
    SourceKind,
)
from app.services.clarifications import answer as answer_clarification
from app.services.review import initial_job_status

PAGES = {
    "dashboard": "/",
    "accounts": "/accounts",
    "library": "/publishing",
    "publishing": "/publishing",
    "agent": "/agent",
    "renders": "/renders",
    "activity": "/activity",
    "calendar": "/calendar",
    "maintenance": "/maintenance",
    "settings": "/settings",
    "operators": "/operators",
    "administration": "/administration",
}

PAGE_ALIASES = {
    "proxies": "accounts",
    "прокси": "accounts",
    "аккаунты": "accounts",
    "библиотека": "library",
    "публикации": "publishing",
    "очередь": "activity",
    "активность": "activity",
    "панель": "dashboard",
    "агент": "agent",
    "рендеры": "renders",
    "календарь": "calendar",
    "обслуживание": "maintenance",
    "настройки": "settings",
    "операторы": "operators",
    "администрирование": "administration",
}


def page_keys() -> list[str]:
    return sorted({*PAGES, *PAGE_ALIASES})


def resolve_page(page: Any) -> tuple[str, str]:
    word = one_word(page)
    key = PAGE_ALIASES.get(word, word)
    try:
        return key, PAGES[key]
    except KeyError:
        raise ToolError(
            f"страницы {page!r} нет; страницы такие: {', '.join(page_keys())}"
        ) from None


def _page_query(page: Any) -> tuple[str, str, dict[str, str]]:
    raw = str(page or "").strip()
    path_part, _, qs = raw.partition("?")
    key, path = resolve_page(path_part)
    query = {k: v for k, v in parse_qsl(qs, keep_blank_values=True) if k} if qs else {}
    return key, path, query

WORD = re.compile(r"[a-z][a-z-]{2,}")
NOISE = frozenset(
    """the and for with from into over under slow fast shot take push pull
    pan tilt drone camera light soft warm cool close wide long very that
    this there here some any all one two three four five""".split()
)
GLOSSARY = {
    "туман": "misty",
    "лес": "forest",
    "горы": "mountain",
    "закат": "sunset",
    "рассвет": "dawn",
    "море": "sea",
    "город": "city",
    "ночь": "night",
    "небо": "sky",
}
LIMIT = 12
MAX_FILE_BYTES = 40_960
LOG_TAIL = 80
DIAGNOSE_LOG_TAIL = 24
SNAPSHOT_LIST_LIMIT = 20
DOCKER_LOG_TIMEOUT = 8
COMPOSE_SERVICES = frozenset(
    {
        "reels-api",
        "reels-worker",
        "reels-ollama",
        "reels-frontend",
        "reels-ollama-pull",
    }
)
COMPOSE_CONTAINERS = {
    "reels-api": "insta-reels-api",
    "reels-worker": "insta-reels-worker",
    "reels-ollama": "insta-reels-ollama",
    "reels-frontend": "insta-reels-frontend",
    "reels-ollama-pull": "insta-reels-ollama-pull",
}
ACCOUNT_LOG_KINDS = frozenset(
    {
        "connection_test",
        "publish_job",
        "first_login",
        "mint_mobile_session",
        "browser_session",
    }
)
DOCKER_SOCK = Path("/var/run/docker.sock")
_PASSWORD_LOG_LINE = re.compile(r"(?i)^(пароль\s*:\s*)(.+)$")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "dist",
        ".venv",
        "venv",
        ".turbo",
    }
)


@dataclass(frozen=True)
class Opened:
    path: str
    query: dict[str, str] | None = None
    what: str = ""
    screenshot_url: str | None = None

    def as_url(self) -> str:
        if not self.query:
            return self.path
        pairs = "&".join(f"{k}={v}" for k, v in self.query.items())
        return f"{self.path}?{pairs}"


class ToolError(Exception):
    pass


def _when(value: datetime | None) -> str | None:
    if value is None:
        return None
    at = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return at.isoformat(timespec="minutes")


def _status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _account_platform(account: Account) -> str:
    return _status_value(account.platform) or "instagram"


def _require_instagram(account: Account, action: str) -> None:
    if _account_platform(account) != "instagram":
        if action == "fingerprint":
            raise ToolError("fingerprint — Android-устройство instagrapi. Только Instagram")
        raise ToolError(
            f"{action} только для Instagram — YouTube и TikTok входят через cookies / браузер в UI"
        )


def overview(db: Session) -> dict[str, Any]:
    counted = dict(db.execute(select(PostJob.status, func.count()).group_by(PostJob.status)).all())
    renders = dict(
        db.execute(select(GenerationJob.status, func.count()).group_by(GenerationJob.status)).all()
    )
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    jobs_awaiting_review = 0
    for status, n in counted.items():
        if _status_value(status) == PostJobStatus.awaiting_review.value:
            jobs_awaiting_review = n
            break
    errors_24h = (
        db.scalar(
            select(func.count(PostJob.id)).where(
                PostJob.status.in_([PostJobStatus.failed, PostJobStatus.dead]),
                PostJob.finished_at >= since,
            )
        )
        or 0
    )
    open_questions = (
        db.scalar(
            select(func.count(Clarification.id)).where(
                Clarification.answer.is_(None),
                Clarification.dismissed.is_(False),
            )
        )
        or 0
    )
    return {
        "accounts": db.scalar(select(func.count()).select_from(Account)) or 0,
        "clips": db.scalar(
            select(func.count()).select_from(MediaAsset).where(MediaAsset.kind == AssetKind.video)
        )
        or 0,
        "soundtracks": db.scalar(
            select(func.count()).select_from(MediaAsset).where(MediaAsset.kind == AssetKind.audio)
        )
        or 0,
        "posts_by_status": {_status_value(s): n for s, n in counted.items()},
        "renders_by_status": {_status_value(s): n for s, n in renders.items()},
        "joins_queued": db.scalar(
            select(func.count())
            .select_from(Composition)
            .where(Composition.status == PipelineStatus.queued)
        )
        or 0,
        "jobs_awaiting_review": jobs_awaiting_review,
        "open_questions": open_questions,
        "errors_24h": errors_24h,
    }


def list_accounts(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(Account).order_by(Account.id)).scalars().all()
    return [_account_public(c) for c in rows]


def account_details(db: Session, account_id: int) -> dict[str, Any]:
    account = _account(db, account_id)
    proxy = account.proxy
    return {
        **_account_public(account),
        "email": account.email,
        "email_password": account.email_password,
        "totp_seed": account.totp_seed,
        "backup_codes": account.backup_codes,
        "session_id": account.session_id,
        "login_identifier": account.login_identifier,
        "login_surface": account.login_surface,
        "notes": account.notes,
        "timezone": account.timezone,
        "daily_post_cap": account.daily_post_cap,
        "min_gap_hours": account.min_gap_hours,
        "active_hour_start": account.active_hour_start,
        "active_hour_end": account.active_hour_end,
        "caption_profile": account.caption_profile,
        "hold_for_review": bool(account.hold_for_review),
        "cooldown_until": _when(account.cooldown_until),
        "proxy": (
            {
                "id": proxy.id,
                "label": proxy.label,
                "url": proxy.url,
                "country": proxy.country,
                "healthy": proxy.is_healthy,
            }
            if proxy is not None
            else None
        ),
    }


def list_posts(
    db: Session,
    *,
    status: str | None = None,
    account_id: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(PostJob).order_by(PostJob.scheduled_for.desc()).limit(LIMIT)
    if status:
        stmt = stmt.where(PostJob.status == _post_status(status))
    if account_id is not None:
        stmt = stmt.where(PostJob.account_id == account_id)
    if query:
        stmt = stmt.where(PostJob.title.ilike(f"%{query}%"))

    names = _account_names(db)
    return [
        {
            "id": j.id,
            "title": j.title,
            "status": _status_value(j.status),
            "account": names.get(j.account_id, f"#{j.account_id}"),
            "scheduled_for": _when(j.scheduled_for),
            "permalink": j.permalink,
            "last_error": j.last_error,
        }
        for j in db.execute(stmt).scalars()
    ]


def list_clips(
    db: Session, *, kind: str = "video", query: str | None = None
) -> list[dict[str, Any]] | dict[str, str]:
    stmt = select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(LIMIT)
    stmt = stmt.where(MediaAsset.kind == _kind(kind))
    if query:
        needle = f"%{query}%"
        stmt = stmt.where(
            MediaAsset.prompt.ilike(needle)
            | MediaAsset.label.ilike(needle)
            | MediaAsset.filename.ilike(needle)
        )
    found = [
        {
            "id": a.id,
            "filename": a.filename,
            "label": a.label or None,
            "prompt": a.prompt,
            "seconds": a.duration_s,
            "source": _status_value(a.source),
            "on_disk": a.file_removed_at is None,
            "created_at": _when(a.created_at),
        }
        for a in db.execute(stmt).scalars()
    ]
    seen = {row["filename"] for row in found}
    if query and _kind(kind) is AssetKind.video:
        from app.config import settings as cfg

        folder = cfg.video_source_dir
        if folder.is_dir():
            needle = query.strip().lower()
            for path in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if not path.is_file() or needle not in path.name.lower() or path.name in seen:
                    continue
                found.append(
                    {
                        "id": None,
                        "filename": path.name,
                        "label": path.name,
                        "prompt": None,
                        "seconds": None,
                        "source": "upload",
                        "on_disk": True,
                        "created_at": None,
                    }
                )
                seen.add(path.name)
                if len(found) >= LIMIT:
                    break
    if found or not query:
        return found
    english = GLOSSARY.get(query.strip().lower())
    if english and english != query:
        again = list_clips(db, kind=kind, query=english)
        if again:
            return again
    return {
        "найдено": "ничего",
        "по запросу": query,
        "слова в библиотеке": vocabulary(db, kind=kind),
        "дальше": "выбери подходящее слово из списка и вызови list_clips ещё раз",
    }


def vocabulary(db: Session, *, kind: str = "video", most: int = 20) -> list[str]:
    rows = db.execute(
        select(MediaAsset.prompt, MediaAsset.label).where(MediaAsset.kind == _kind(kind))
    ).all()
    seen: Counter[str] = Counter()
    for prompt, label in rows:
        for word in WORD.findall(f"{prompt or ''} {label or ''}".lower()):
            if word not in NOISE:
                seen[word] += 1
    return [word for word, _ in seen.most_common(most)]


def list_renders(db: Session, *, status: str | None = None) -> list[dict[str, Any]]:
    stmt = select(GenerationJob).order_by(GenerationJob.created_at.desc()).limit(LIMIT)
    if status:
        stmt = stmt.where(GenerationJob.status == _pipeline_status(status))
    return [
        {
            "id": g.id,
            "prompt": g.prompt,
            "status": _status_value(g.status),
            "stage": g.stage or None,
            "cost_usd": g.cost_usd,
            "asset_id": g.asset_id,
            "last_error": g.last_error,
            "backend": g.backend,
        }
        for g in db.execute(stmt).scalars()
    ]


def list_compositions(db: Session, *, status: str | None = None) -> list[dict[str, Any]]:
    stmt = select(Composition).order_by(Composition.created_at.desc()).limit(LIMIT)
    if status:
        stmt = stmt.where(Composition.status == _pipeline_status(status))
    return [
        {
            "id": c.id,
            "status": _status_value(c.status),
            "post_title": c.post_title,
            "clips": len(c.clips),
            "last_error": c.last_error,
        }
        for c in db.execute(stmt).scalars()
    ]


def list_proxies(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(Proxy).order_by(Proxy.id)).scalars().all()
    counts = dict(
        db.execute(
            select(Account.proxy_id, func.count())
            .where(Account.proxy_id.is_not(None))
            .group_by(Account.proxy_id)
        ).all()
    )
    return [
        {
            "id": p.id,
            "label": p.label,
            "url": p.url,
            "country": p.country,
            "healthy": p.is_healthy,
            "last_ip": p.last_known_ip,
            "accounts": int(counts.get(p.id, 0)),
        }
        for p in rows
    ]


def list_operators(db: Session, *, as_owner: bool = True) -> dict[str, Any]:
    from app.config import settings
    from app.panel.settings_store import get_or_create_panel_settings

    panel = get_or_create_panel_settings(db)
    rows = db.scalars(select(PanelOperator).order_by(PanelOperator.created_at.desc())).all()
    operators = [
        {
            "id": row.id,
            "label": row.label,
            "active": row.revoked_at is None,
            "created_at": _when(row.created_at),
            "revoked_at": _when(row.revoked_at),
            "last_used_at": _when(row.last_used_at),
        }
        for row in rows
    ]
    auth_required = bool(settings.admin_token) or bool(panel.master_password_hash)
    if not as_owner:
        return {
            "how": (
                "Операторы — отдельные пароли на странице Доступы; отозванный оператор "
                "больше не входит. Секретный URL и токен владельца чат оператору не показывает."
            ),
            "auth_required": auth_required,
            "operators": operators,
        }
    return {
        "how": (
            "Панель открывается по секретному URL (entry_path). Владелец входит "
            "токеном ADMIN_TOKEN / master password. Операторы — отдельные пароли "
            "на странице Доступы; отозванный оператор больше не входит."
        ),
        "entry_path": panel.entry_path,
        "owner_token": settings.admin_token or None,
        "auth_required": auth_required,
        "operators": operators,
    }


def list_project_files(path: str | None = None) -> dict[str, Any]:
    folder = _inside_project(path or ".")
    if not folder.exists():
        raise ToolError(f"пути {path!r} нет")
    if not folder.is_dir():
        raise ToolError(f"{path!r} — не папка; для файла используй read_project_file")
    names: list[dict[str, Any]] = []
    for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if child.name in SKIP_DIRS or child.name.startswith("."):
            if child.name not in {".env", ".env.example"}:
                continue
        names.append(
            {
                "name": child.name,
                "kind": "dir" if child.is_dir() else "file",
                "path": _rel_to_project(child),
            }
        )
        if len(names) >= 80:
            break
    return {"path": _rel_to_project(folder), "entries": names}


def read_project_file(path: str) -> dict[str, Any]:
    target = _inside_project(path)
    if not target.exists() or not target.is_file():
        raise ToolError(f"файла {path!r} нет")
    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ToolError(f"файл больше {MAX_FILE_BYTES} байт — открой кусок меньше или другой файл")
    raw = target.read_bytes()
    if b"\x00" in raw[:1024]:
        raise ToolError("это бинарный файл, его не читаю")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError("файл не в UTF-8") from exc
    return {"path": _rel_to_project(target), "bytes": size, "text": text}


def list_errors(db: Session, *, limit: int = LIMIT) -> dict[str, Any]:
    events = db.scalars(
        select(Event)
        .where(Event.level.in_((EventLevel.warn, EventLevel.error, EventLevel.critical)))
        .order_by(Event.created_at.desc())
        .limit(limit)
    ).all()
    posts = db.scalars(
        select(PostJob)
        .where(PostJob.status.in_((PostJobStatus.failed, PostJobStatus.dead)))
        .order_by(PostJob.scheduled_for.desc())
        .limit(limit)
    ).all()
    renders = db.scalars(
        select(GenerationJob)
        .where(GenerationJob.status.in_((PipelineStatus.failed, PipelineStatus.dead)))
        .order_by(GenerationJob.created_at.desc())
        .limit(limit)
    ).all()
    names = _account_names(db)
    return {
        "events": [
            {
                "id": e.id,
                "level": _status_value(e.level),
                "kind": e.kind,
                "account": names.get(e.account_id) if e.account_id else None,
                "message": e.message,
                "at": _when(e.created_at),
            }
            for e in events
        ],
        "failed_posts": [
            {
                "id": j.id,
                "title": j.title,
                "status": _status_value(j.status),
                "account": names.get(j.account_id, f"#{j.account_id}"),
                "last_error": j.last_error,
            }
            for j in posts
        ],
        "failed_renders": [
            {
                "id": g.id,
                "prompt": g.prompt,
                "status": _status_value(g.status),
                "last_error": g.last_error,
            }
            for g in renders
        ],
    }


def job_logs(db: Session, job_id: int, *, tail: int = 40) -> tuple[dict[str, Any], Opened]:
    from app.diagnostics.collector import load_run_lines

    job = db.get(PostJob, job_id)
    if job is None:
        raise ToolError(f"публикации {job_id} нет")
    runs = db.scalars(
        select(DiagnosticRun)
        .where(DiagnosticRun.job_id == job_id)
        .order_by(DiagnosticRun.created_at.asc())
    ).all()
    payload: list[dict[str, Any]] = []
    for run in runs:
        lines = load_run_lines(run)
        payload.append(
            {
                "run_id": run.id,
                "status": _status_value(run.status),
                "summary": run.summary,
                "lines": [
                    {"level": line.level, "step": line.step, "message": line.message}
                    for line in lines[-tail:]
                ],
            }
        )
    opened = Opened(path="/activity", query={"job": str(job.id)}, what=job.title or str(job.id))
    return (
        {
            "job_id": job.id,
            "status": _status_value(job.status),
            "last_error": job.last_error,
            "runs": payload,
        },
        opened,
    )


def _redact_diag_message(message: str) -> str:
    match = _PASSWORD_LOG_LINE.match((message or "").strip())
    if not match:
        return message
    value = (match.group(2) or "").strip()
    if value in ("", "—", "-", "***"):
        return message
    return f"{match.group(1)}***"


def account_logs(
    db: Session,
    account_id: int,
    *,
    kind: Any = None,
    tail: int = 40,
) -> tuple[dict[str, Any], Opened]:
    from app.diagnostics.collector import load_run_lines

    account = _account(db, account_id)
    try:
        n = int(tail or 40)
    except (TypeError, ValueError):
        n = 40
    n = max(1, min(n, 80))
    stmt = select(DiagnosticRun).where(DiagnosticRun.account_id == account.id)
    raw_kind = str(kind or "").strip()
    if raw_kind:
        if raw_kind not in ACCOUNT_LOG_KINDS:
            raise ToolError(
                f"kind {kind!r} нет; можно: {', '.join(sorted(ACCOUNT_LOG_KINDS))}"
            )
        try:
            kind_enum = DiagnosticRunKind(raw_kind)
        except ValueError as exc:
            raise ToolError(f"kind {kind!r} нет") from exc
        stmt = stmt.where(DiagnosticRun.kind == kind_enum)
    stmt = stmt.order_by(DiagnosticRun.created_at.desc()).limit(LIMIT)
    runs = db.scalars(stmt).all()
    payload: list[dict[str, Any]] = []
    for run in runs:
        lines = load_run_lines(run)
        payload.append(
            {
                "run_id": run.id,
                "kind": _status_value(run.kind),
                "status": _status_value(run.status),
                "summary": run.summary,
                "at": _when(run.created_at),
                "lines": [
                    {
                        "level": line.level,
                        "step": line.step,
                        "message": _redact_diag_message(line.message),
                    }
                    for line in lines[-n:]
                ],
            }
        )
    opened = Opened(path="/accounts", query={"id": str(account.id)}, what=account.username)
    return (
        {
            "account_id": account.id,
            "username": account.username,
            "runs": payload,
        },
        opened,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _clip_list(rows: list[Any], key: str) -> dict[str, Any]:
    clipped = rows[:SNAPSHOT_LIST_LIMIT]
    payload: dict[str, Any] = {key: clipped}
    omitted = len(rows) - len(clipped)
    if omitted:
        payload[f"{key}_omitted"] = omitted
    return payload


def _merge_hints(*blocks: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        for hint in block.get("hints") or []:
            if hint not in seen:
                seen.add(hint)
                out.append(hint)
    return out


def _posting_snapshot(db: Session, *, queue_idle: bool, foreign_alive: bool) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    counted = dict(db.execute(select(PostJob.status, func.count()).group_by(PostJob.status)).all())
    posts_by_status = {_status_value(s): n for s, n in counted.items()}
    awaiting_review = int(posts_by_status.get(PostJobStatus.awaiting_review.value, 0))
    running = int(posts_by_status.get(PostJobStatus.running.value, 0))
    failed_dead = int(posts_by_status.get(PostJobStatus.failed.value, 0)) + int(
        posts_by_status.get(PostJobStatus.dead.value, 0)
    )

    queued_due = 0
    queued = db.scalars(select(PostJob).where(PostJob.status == PostJobStatus.queued)).all()
    for job in queued:
        when = _aware(job.scheduled_for)
        if when is not None and when <= now:
            queued_due += 1

    not_active = (
        AccountStatus.challenge,
        AccountStatus.cooldown,
        AccountStatus.blocked,
        AccountStatus.paused,
    )
    accounts_not_active = [
        {"id": a.id, "username": a.username, "status": _status_value(a.status)}
        for a in db.scalars(select(Account).where(Account.status.in_(not_active)).order_by(Account.id)).all()
    ]
    proxies_unhealthy = [
        {"id": p.id, "label": p.label}
        for p in db.scalars(select(Proxy).where(Proxy.is_healthy.is_(False)).order_by(Proxy.id)).all()
    ]

    hints: list[str] = []
    if queued_due and queue_idle:
        hints.append("очередь queued_due при мёртвом воркере — start_worker")
    if queued_due and foreign_alive:
        hints.append("чужой воркер жив (Docker/терминал) — не start_worker, очередь должна ехать")
    if awaiting_review:
        hints.append("ждут approve_job (hold_for_review)")
    if failed_dead:
        hints.append("failed/dead публикации — job_logs по id")
    if accounts_not_active:
        hints.append("аккаунт не active — account_logs / test_connection")
    if proxies_unhealthy:
        hints.append("прокси unhealthy — test_proxy; не списывать любую ошибку на прокси")

    out: dict[str, Any] = {
        "hints": hints,
        "posts_by_status": posts_by_status,
        "queued_due": queued_due,
        "awaiting_review": awaiting_review,
        "running": running,
    }
    out.update(_clip_list(accounts_not_active, "accounts_not_active"))
    out.update(_clip_list(proxies_unhealthy, "proxies_unhealthy"))
    return out


_LOGIN_RUN_KINDS = (
    DiagnosticRunKind.first_login,
    DiagnosticRunKind.connection_test,
    DiagnosticRunKind.mint_mobile_session,
    DiagnosticRunKind.browser_session,
)
_NOT_ACTIVE = (
    AccountStatus.challenge,
    AccountStatus.cooldown,
    AccountStatus.blocked,
    AccountStatus.paused,
)
_LOGIN_BLOCKED = (AccountStatus.challenge, AccountStatus.cooldown, AccountStatus.blocked)


def _session_missing(account: Account) -> bool:
    from app.accounts.cookie_formats import STUDIO_PLATFORMS, studio_session_ready
    from app.accounts.session_export import export_sessionid

    platform = _account_platform(account)
    if platform in STUDIO_PLATFORMS:
        return not studio_session_ready(account.username, platform)
    return export_sessionid(account.username, db_session_id=account.session_id) is None


def _login_snapshot(db: Session) -> dict[str, Any]:
    accounts = list(db.scalars(select(Account).order_by(Account.id)).all())
    counted: dict[str, int] = {}
    not_active: list[dict[str, Any]] = []
    no_proxy: list[dict[str, Any]] = []
    missing_session: list[dict[str, Any]] = []
    missing_ig = False
    missing_studio = False
    blocked_login = False
    for account in accounts:
        status = _status_value(account.status)
        counted[status] = counted.get(status, 0) + 1
        platform = _account_platform(account)
        row = {
            "id": account.id,
            "username": account.username,
            "status": status,
            "platform": platform,
        }
        if account.status in _NOT_ACTIVE:
            not_active.append({**row, "cooldown_until": _when(account.cooldown_until)})
        if account.status in _LOGIN_BLOCKED:
            blocked_login = True
        if account.proxy_id is None:
            no_proxy.append({"id": account.id, "username": account.username, "platform": platform})
        if _session_missing(account):
            missing_session.append({"id": account.id, "username": account.username, "platform": platform})
            if platform in ("youtube", "tiktok"):
                missing_studio = True
            else:
                missing_ig = True

    failed_stmt = (
        select(DiagnosticRun, Account)
        .join(Account, Account.id == DiagnosticRun.account_id)
        .where(
            DiagnosticRun.kind.in_(_LOGIN_RUN_KINDS),
            DiagnosticRun.status.in_((DiagnosticRunStatus.fail, DiagnosticRunStatus.warn)),
        )
        .order_by(DiagnosticRun.created_at.desc())
    )
    failed_runs = [
        {
            "account_id": account.id,
            "username": account.username,
            "kind": _status_value(run.kind),
            "status": _status_value(run.status),
            "summary": _redact_diag_message(run.summary or ""),
            "at": _when(run.created_at),
        }
        for run, account in db.execute(failed_stmt).all()
    ]

    hints: list[str] = []
    if blocked_login:
        hints.append("аккаунт challenge/cooldown/blocked — account_logs (first_login / connection_test)")
    if missing_ig:
        hints.append("нет сессии Instagram — get_session / first_login")
    if missing_studio:
        hints.append("нет state.json Studio — import_cookies или start_browser в run")
    if failed_runs:
        hints.append("failed diagnostic runs — account_logs по id")
    if no_proxy:
        hints.append("нет proxy_id — attach_proxy / ask_operator")

    out: dict[str, Any] = {
        "hints": hints,
        "accounts_by_status": counted,
    }
    out.update(_clip_list(not_active, "not_active"))
    out.update(_clip_list(no_proxy, "no_proxy"))
    out.update(_clip_list(missing_session, "missing_session"))
    out.update(_clip_list(failed_runs, "failed_runs"))
    return out


def _proxies_snapshot(db: Session) -> dict[str, Any]:
    from app.geo.country_codes import countries_mismatch

    proxies = list(db.scalars(select(Proxy).order_by(Proxy.id)).all())
    unhealthy: list[dict[str, Any]] = []
    never_checked: list[dict[str, Any]] = []
    geo_mismatch: list[dict[str, Any]] = []
    unhealthy_ids: set[int] = set()
    labels: dict[int, str] = {}
    for proxy in proxies:
        labels[proxy.id] = proxy.label
        row = {
            "id": proxy.id,
            "label": proxy.label,
            "last_checked_at": _when(proxy.last_checked_at),
            "advertised_country": proxy.country,
            "last_geo_country": proxy.last_geo_country,
        }
        if not proxy.is_healthy:
            unhealthy.append(row)
            unhealthy_ids.add(proxy.id)
        if proxy.last_checked_at is None:
            never_checked.append({"id": proxy.id, "label": proxy.label})
        if countries_mismatch(proxy.country, proxy.last_geo_country):
            geo_mismatch.append(
                {
                    "id": proxy.id,
                    "label": proxy.label,
                    "advertised_country": proxy.country,
                    "last_geo_country": proxy.last_geo_country,
                }
            )

    accounts_on_unhealthy = (
        [
            {
                "id": account.id,
                "username": account.username,
                "label": labels.get(account.proxy_id) or "",
            }
            for account in db.scalars(
                select(Account).where(Account.proxy_id.in_(unhealthy_ids)).order_by(Account.id)
            ).all()
        ]
        if unhealthy_ids
        else []
    )

    hints: list[str] = []
    if unhealthy:
        hints.append("прокси unhealthy — test_proxy; не списывать любую ошибку на прокси")
    if never_checked:
        hints.append("прокси never_checked — test_proxy")
    if geo_mismatch:
        hints.append("geo_mismatch advertised vs last_geo_country — цитировать страны, TZ не выдумывать")

    out: dict[str, Any] = {"hints": hints}
    out.update(_clip_list(unhealthy, "unhealthy"))
    out.update(_clip_list(never_checked, "never_checked"))
    out.update(_clip_list(geo_mismatch, "geo_mismatch"))
    out.update(_clip_list(accounts_on_unhealthy, "accounts_on_unhealthy"))
    return out


def diagnose(db: Session, *, tail: int = DIAGNOSE_LOG_TAIL) -> dict[str, Any]:
    from app.config import get_settings
    from app.scheduler.heartbeat import worker_status
    from app.services import runtime, worker_control

    settings = get_settings()
    running = worker_control.status()
    beat = worker_status(db)
    ollama = runtime.probe(settings)
    log_path = Path(settings.log_file) if settings.log_file else None
    app_log, app_log_reason = _tail_log(log_path, tail)
    foreign_alive = beat.known and not beat.stale and not running.alive
    queue_idle = (not running.alive) and (not beat.known or beat.stale)
    posting = _posting_snapshot(db, queue_idle=queue_idle, foreign_alive=foreign_alive)
    login = _login_snapshot(db)
    proxies = _proxies_snapshot(db)
    return {
        "hints": _merge_hints(posting, login, proxies),
        "worker": {
            "ours_alive": running.alive,
            "pid": running.pid,
            "heartbeat_known": beat.known,
            "seen_at": _when(beat.seen_at),
            "stale": beat.stale,
            "foreign_alive": foreign_alive,
            "note": beat.note,
        },
        "posting": posting,
        "login": login,
        "proxies": proxies,
        "ollama": {
            "reachable": ollama.reachable,
            "base_url": ollama.base_url,
            "models": ollama.models,
            "loaded": [
                {"name": one.name, "context": one.context, "size_bytes": one.size_bytes}
                for one in ollama.loaded
            ],
            "detail": ollama.detail,
        },
        "errors": list_errors(db),
        "render_backends": list_render_backends(),
        "app_log": app_log,
        "app_log_reason": app_log_reason,
    }


def docker_logs(service: Any, *, tail: int = LOG_TAIL) -> dict[str, Any]:
    name = one_word(service)
    if name not in COMPOSE_SERVICES:
        raise ToolError(
            f"сервиса {service!r} нет; можно: {', '.join(sorted(COMPOSE_SERVICES))}"
        )
    try:
        n = int(tail or LOG_TAIL)
    except (TypeError, ValueError):
        n = LOG_TAIL
    n = max(1, min(n, 200))
    compose = _docker_compose_logs(name, n)
    if compose.get("available"):
        return compose
    engine = _docker_engine_logs(COMPOSE_CONTAINERS[name], n)
    if engine.get("available"):
        engine["service"] = name
        engine["source"] = "engine"
        return engine
    reasons = [r for r in (compose.get("reason"), engine.get("reason")) if r]
    return {
        "available": False,
        "service": name,
        "reason": "; ".join(reasons) or "логи docker недоступны",
        "lines": [],
    }


def _docker_compose_logs(name: str, n: int) -> dict[str, Any]:
    if not COMPOSE_FILE.is_file():
        return {
            "available": False,
            "service": name,
            "reason": f"нет файла {COMPOSE_FILE.as_posix()}",
            "lines": [],
        }
    cmd = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "logs",
        "--no-color",
        f"--tail={n}",
        name,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=DOCKER_LOG_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "service": name,
            "reason": "Docker CLI не найден",
            "lines": [],
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "service": name,
            "reason": f"docker compose logs не ответил за {DOCKER_LOG_TIMEOUT} с",
            "lines": [],
        }
    err = (proc.stderr or "").strip()
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return {
            "available": False,
            "service": name,
            "reason": err or f"docker compose logs exit {proc.returncode}",
            "lines": [],
        }
    lines = out.splitlines()[-n:] if out else []
    payload: dict[str, Any] = {"available": True, "service": name, "lines": lines}
    if not lines:
        payload["reason"] = "контейнер есть, но логов нет (или compose не запускали)"
    return payload


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


def _decode_docker_log_stream(raw: bytes) -> str:
    if not raw:
        return ""
    multiplexed = len(raw) >= 8 and raw[0] in (0, 1, 2) and raw[1:4] == b"\x00\x00\x00"
    if not multiplexed:
        return raw.decode("utf-8", errors="replace")
    chunks: list[bytes] = []
    i = 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        start = i + 8
        end = start + size
        if end > len(raw):
            chunks.append(raw[start:])
            break
        chunks.append(raw[start:end])
        i = end
    return b"".join(chunks).decode("utf-8", errors="replace")


def _docker_engine_logs(container: str, tail: int) -> dict[str, Any]:
    if not hasattr(socket, "AF_UNIX"):
        return {"available": False, "reason": "нет unix-сокетов", "lines": []}
    if not DOCKER_SOCK.exists():
        return {"available": False, "reason": f"нет {DOCKER_SOCK.as_posix()}", "lines": []}
    path = f"/containers/{quote(container, safe='')}/logs?stdout=1&stderr=1&timestamps=0&tail={int(tail)}"
    conn: _UnixHTTPConnection | None = None
    try:
        conn = _UnixHTTPConnection(str(DOCKER_SOCK), timeout=DOCKER_LOG_TIMEOUT)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        if resp.status == 404:
            return {
                "available": False,
                "reason": f"контейнера {container} нет",
                "lines": [],
            }
        if resp.status >= 400:
            detail = body.decode("utf-8", errors="replace").strip() or f"HTTP {resp.status}"
            return {"available": False, "reason": detail, "lines": []}
        text = _decode_docker_log_stream(body).strip()
        lines = text.splitlines()[-tail:] if text else []
        payload: dict[str, Any] = {"available": True, "lines": lines}
        if not lines:
            payload["reason"] = f"контейнер {container} есть, но логов нет"
        return payload
    except OSError as exc:
        return {"available": False, "reason": str(exc) or "docker.sock недоступен", "lines": []}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": str(exc), "lines": []}
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


def _tail_file_lines(path: Path, n: int, *, chunk: int = 8192) -> list[str]:
    """Last *n* lines; reads from the end of the file, not the whole contents."""
    with path.open("rb") as fh:
        fh.seek(0, 2)
        pos = fh.tell()
        if pos == 0:
            return []
        buf = b""
        while pos > 0 and buf.count(b"\n") <= n:
            step = min(chunk, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
    text = buf.decode("utf-8", errors="replace")
    return text.splitlines()[-n:]


def _tail_log(path: Path | None, tail: int) -> tuple[list[str] | None, str | None]:
    if path is None:
        return None, "log_file не задан"
    target = Path(path)
    if not target.is_file():
        return None, f"файла нет: {_rel_to_project(target)}"
    try:
        n = max(1, min(int(tail or LOG_TAIL), 200))
    except (TypeError, ValueError):
        n = LOG_TAIL
    try:
        return _tail_file_lines(target, n), None
    except OSError as exc:
        return None, str(exc)


def open_page(page: Any) -> Opened:
    key, path, query = _page_query(page)
    return Opened(path=path, query=query or None, what=key)


def open_clip(db: Session, asset_id: int) -> Opened:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise ToolError(f"клипа {asset_id} нет")
    return Opened(
        path="/publishing",
        query={"asset": str(asset_id)},
        what=asset.label or asset.prompt or asset.filename,
    )


def open_post(db: Session, job_id: int) -> Opened:
    job = db.get(PostJob, job_id)
    if job is None:
        raise ToolError(f"публикации {job_id} нет")
    return Opened(path="/activity", query={"job": str(job_id)}, what=job.title or str(job.id))


def open_account(db: Session, account_id: int) -> Opened:
    account = db.get(Account, account_id)
    if account is None:
        raise ToolError(f"аккаунта {account_id} нет")
    return Opened(
        path="/accounts",
        query={"id": str(account.id)},
        what=account.username,
    )


def screenshot_page(
    page: Any,
    *,
    settings: Settings | None = None,
    db: Session | None = None,
    token: str | None = None,
) -> Opened:
    from app.services import panel_browser

    word, path = resolve_page(page)
    try:
        filename = panel_browser.capture(path, settings=settings, db=db, token=token)
    except panel_browser.BrowserError as exc:
        raise ToolError(str(exc)) from None
    return Opened(
        path=path,
        what=f"the {word} page",
        screenshot_url=panel_browser.signed_url(filename, settings),
    )


def plan_account(
    db: Session,
    account_id: int,
    *,
    count: int = 5,
    week: bool = False,
    duration_s: float | None = None,
    auto_schedule: bool | None = None,
) -> dict[str, Any]:
    account = _account(db, account_id)
    seconds = 5.0 if duration_s is None else float(duration_s)
    seconds = max(5.0, min(seconds, 10.0))
    schedule = True if auto_schedule is None else bool(auto_schedule)
    job = PlanJob(
        account_id=account.id,
        count=max(1, min(count, 20)),
        duration_s=seconds,
        auto_schedule=schedule,
        spread_over_days=7 if week else None,
        status=PipelineStatus.queued,
        scheduled_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    out = {
        "queued_plan_id": job.id,
        "account": account.username,
        "count": job.count,
        "week": week,
        "duration_s": job.duration_s,
        "auto_schedule": job.auto_schedule,
    }
    if not _worker_running(db):
        out["предупреждение"] = "воркер стоит, план в очереди"
    return out


def preview_plan(
    db: Session,
    account_id: int,
    *,
    count: int = 5,
    duration_s: float | None = None,
) -> dict[str, Any]:
    from app.services.planning import plan_for_channel

    account = _account(db, account_id)
    seconds = 5.0 if duration_s is None else float(duration_s)
    seconds = max(5.0, min(seconds, 10.0))
    try:
        jobs = plan_for_channel(
            db,
            account,
            max(1, min(count, 20)),
            duration_s=seconds,
            auto_schedule=False,
        )
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    return {"planned": len(jobs), "job_ids": [j.id for j in jobs]}


def enqueue_publish(
    db: Session,
    *,
    account_id: int,
    filename: str | None = None,
    asset_id: int | None = None,
    title: str = "",
    caption: str | None = None,
    caption_template: str | None = None,
    description: str | None = None,
    tags: str | None = None,
    post_type: str | None = None,
    when: Any = None,
) -> dict[str, Any]:
    from app.config import settings
    from app.services.scheduling import post_type_for

    account = _account(db, account_id)
    path: Path | None = None
    if asset_id is not None:
        asset = db.get(MediaAsset, asset_id)
        if asset is None:
            raise ToolError(f"клипа {asset_id} нет")
        path = (settings.media_dir / asset.filename).resolve()
        title = title or asset.label or asset.filename
        filename = asset.filename
    elif filename:
        safe = Path(filename).name
        path = (settings.video_source_dir / safe).resolve()
        title = title or safe
    else:
        raise ToolError("нужен filename или asset_id")
    if path is None or not path.is_file():
        raise ToolError(f"файл {filename} не найден в библиотеке")

    kind = _parse_post_type(post_type) if post_type else post_type_for(account)
    caption_text = caption if caption is not None else caption_template
    if caption_text is None:
        caption_text = title
    scheduled = _parse_when(when) or datetime.now(timezone.utc)
    job = PostJob(
        account_id=account.id,
        source_video_path=str(path),
        post_type=kind,
        title=title,
        caption_template=caption_text,
        description=description or "",
        tags=tags or "",
        scheduled_for=scheduled,
        status=initial_job_status(account),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {
        "job_id": job.id,
        "account": account.username,
        "file": path.name,
        "status": job.status.value,
        "post_type": _status_value(job.post_type),
        "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None,
    }


def reschedule_job(db: Session, job_id: int, *, when: Any) -> dict[str, Any]:
    job = db.get(PostJob, job_id)
    if job is None:
        raise ToolError(f"публикации {job_id} нет")
    if job.status not in (
        PostJobStatus.queued,
        PostJobStatus.awaiting_review,
        PostJobStatus.failed,
    ):
        raise ToolError(f"задачу в состоянии «{job.status.value}» перенести нельзя")
    scheduled = _parse_when(when)
    if scheduled is None:
        return {
            "ask": True,
            "questions": ["на какую дату/время (ISO, например 2026-09-12T18:00:00)?"],
            "why": "чтобы перенести слот",
        }
    job.scheduled_for = scheduled
    db.commit()
    db.refresh(job)
    return {
        "job_id": job.id,
        "status": job.status.value,
        "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None,
    }


def pause_account(db: Session, account_id: int) -> dict[str, Any]:
    account = _account(db, account_id)
    account.status = AccountStatus.paused
    db.commit()
    return {"id": account.id, "username": account.username, "status": "paused"}


def resume_account(db: Session, account_id: int) -> dict[str, Any]:
    account = _account(db, account_id)
    account.cooldown_until = None
    account.status = AccountStatus.active
    db.commit()
    return {"id": account.id, "username": account.username, "status": "active"}


def _confirmed(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    word = one_word(raw)
    return word in {"true", "1", "yes", "да", "ок", "подтверждаю", "подтвердить"}


def _need_confirm(question: str, why: str) -> dict[str, Any]:
    return {"ask": True, "questions": [question], "why": why}


def approve_job(db: Session, job_id: int) -> dict[str, Any]:
    from app.services.review import NotHeld, approve

    job = db.get(PostJob, job_id)
    if job is None:
        raise ToolError(f"публикации {job_id} нет")
    try:
        approve(db, job)
    except NotHeld as exc:
        raise ToolError(str(exc)) from exc
    return {"id": job.id, "status": _status_value(job.status), "title": job.title or ""}


def cancel_job(db: Session, job_id: int, *, confirm: Any = False) -> dict[str, Any]:
    job = db.get(PostJob, job_id)
    if job is None:
        raise ToolError(f"публикации {job_id} нет")
    title = job.title or str(job.id)
    if not _confirmed(confirm):
        return _need_confirm(
            f"Отменить публикацию {job.id} «{title}»?",
            "отмена убирает задачу из очереди",
        )
    if job.status not in (PostJobStatus.queued, PostJobStatus.failed, PostJobStatus.awaiting_review):
        raise ToolError(f"нельзя отменить публикацию в состоянии «{job.status.value}»")
    job.status = PostJobStatus.cancelled
    db.commit()
    db.refresh(job)
    return {"id": job.id, "status": "cancelled", "title": title}


def retry_job(db: Session, job_id: int) -> dict[str, Any]:
    from app.services.retry import NotRetriable, revive

    job = db.get(PostJob, job_id)
    if job is None:
        raise ToolError(f"публикации {job_id} нет")
    try:
        revive(job)
    except NotRetriable as exc:
        raise ToolError(str(exc)) from exc
    db.commit()
    db.refresh(job)
    return {"id": job.id, "status": _status_value(job.status), "title": job.title or ""}


def _worker_running(db: Session) -> bool:
    from app.scheduler.heartbeat import worker_status
    from app.services import worker_control

    beat = worker_status(db)
    ours = worker_control.status()
    return bool(ours.alive or (beat.known and not beat.stale))


def _geo_fields(proxy: Proxy, snapshot: object | None) -> dict[str, Any]:
    from app.geo.country_codes import countries_mismatch

    actual = getattr(snapshot, "country", None) if snapshot is not None else None
    return {
        "geo_mismatch": bool(countries_mismatch(proxy.country, actual)) if snapshot is not None else False,
        "advertised_country": proxy.country,
        "actual_country": actual,
    }


def start_worker(db: Session) -> dict[str, Any]:
    from app.scheduler.heartbeat import worker_status
    from app.services import worker_control

    beat = worker_status(db)
    ours = worker_control.status()
    if beat.known and not beat.stale and not ours.alive:
        return {
            "running": True,
            "ours": False,
            "skipped": True,
            "pid": ours.pid,
            "note": beat.note,
            "сообщение": "очередь уже крутит чужой процесс (Docker/терминал), start не нужен",
        }
    try:
        worker_control.start()
    except worker_control.WorkerProblem as exc:
        raise ToolError(str(exc)) from exc
    ours = worker_control.status()
    beat = worker_status(db)
    return {
        "running": ours.alive or (beat.known and not beat.stale),
        "ours": ours.alive,
        "pid": ours.pid,
        "note": beat.note,
    }


def stop_worker(db: Session, *, confirm: Any = False) -> dict[str, Any]:
    from app.scheduler.heartbeat import worker_status
    from app.services import worker_control

    if not _confirmed(confirm):
        return _need_confirm("Остановить воркер?", "публикации перестанут ехать, пока его снова не запустят")
    ours = worker_control.status()
    if not ours.alive:
        raise ToolError("Панель может остановить только агента, которого запустила сама.")
    worker_control.stop()
    beat = worker_status(db)
    ours = worker_control.status()
    return {
        "running": ours.alive or (beat.known and not beat.stale),
        "ours": ours.alive,
        "pid": ours.pid,
        "note": beat.note,
    }


def take_backup() -> dict[str, Any]:
    from app.services.backup import BackupError, take

    try:
        backup = take()
    except BackupError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "name": backup.database.name,
        "bytes": backup.bytes,
        "taken_at": backup.taken_at.isoformat(),
    }


def test_proxy(db: Session, proxy_label: str) -> dict[str, Any]:
    from app.proxies.pool import health_check_record

    proxy = _proxy_by_label(db, proxy_label)
    ok, snapshot, err = health_check_record(db, proxy)
    return {
        "label": proxy.label,
        "ok": ok,
        "error": err,
        "ip": snapshot.ip if snapshot else None,
        "country": snapshot.country if snapshot else None,
        **_geo_fields(proxy, snapshot),
    }


def test_connection(db: Session, account_id: int, *, probe_mobile: bool = False) -> dict[str, Any]:
    from app.accounts.connection_test import run_account_connection_test

    account = _account(db, account_id)
    platform = _account_platform(account)
    if probe_mobile and platform != "instagram":
        raise ToolError("probe_mobile только для Instagram")
    out = run_account_connection_test(account, db, probe_mobile=bool(probe_mobile))
    proxy_err = out.proxy_health.error if out.proxy_health else None
    auth_err = out.instagram_auth.error if out.instagram_auth else None
    payload: dict[str, Any] = {
        "username": out.username,
        "platform": platform,
        "ok": out.overall_ok,
        "proxy_label": out.proxy_label,
        "proxy_ok": out.proxy_health.ok if out.proxy_health else False,
        "error": auth_err or proxy_err,
        "run_id": out.run_id,
        "geo_mismatch": bool(getattr(out.proxy_health, "geo_mismatch", False)) if out.proxy_health else False,
        "advertised_country": account.proxy.country if account.proxy is not None else None,
        "actual_country": getattr(out.proxy_health, "geo_country", None) if out.proxy_health else None,
    }
    if platform == "instagram":
        payload["instagram_ok"] = out.instagram_auth.ok if out.instagram_auth else False
    else:
        payload["session_ok"] = out.instagram_auth.ok if out.instagram_auth else False
        if out.overall_ok:
            payload["note"] = "cookies Studio на диске (живость на сервере не проверялась)"
    return payload


def _file_format(raw: Any) -> str:
    word = one_word(raw) or "json"
    if word not in {"json", "txt"}:
        raise ToolError("format должен быть json или txt")
    return word


def _download_open(account: Account, download: str, fmt: str) -> Opened:
    query = {"id": str(account.id), "download": download}
    if fmt != "json":
        query["format"] = fmt
    return Opened(path="/accounts", query=query, what=account.username)


def export_cookies(db: Session, account_id: int, *, format: str = "json") -> tuple[dict[str, Any], Opened]:
    from app.accounts.cookie_formats import CookieFormatError, write_dolphin_cookies_export

    account = _account(db, account_id)
    fmt = _file_format(format)
    platform = _account_platform(account)
    try:
        write_dolphin_cookies_export(
            account.username,
            db_session_id=account.session_id,
            as_txt=fmt == "txt",
            platform=platform,
        )
    except CookieFormatError as exc:
        raise ToolError(str(exc)) from exc
    opened = _download_open(account, "cookies", fmt)
    return (
        {
            "username": account.username,
            "скачивается": "в браузере",
            "download": "cookies",
            "format": fmt,
            "api": f"/api/accounts/{account.username}/cookies/export",
        },
        opened,
    )


def export_fingerprint(
    db: Session, account_id: int, *, format: str = "json"
) -> tuple[dict[str, Any], Opened]:
    from app.accounts.device_factory import device_path, load_fingerprint

    account = _account(db, account_id)
    _require_instagram(account, "fingerprint")
    fmt = _file_format(format)
    path = device_path(account.username)
    if not path.exists() and load_fingerprint(account.username) is None:
        raise ToolError("Device fingerprint не найден для этого аккаунта")
    opened = _download_open(account, "fingerprint", fmt)
    return (
        {
            "username": account.username,
            "скачивается": "в браузере",
            "download": "fingerprint",
            "format": fmt,
            "api": f"/api/accounts/{account.username}/device-fingerprint",
        },
        opened,
    )


def export_playwright_state(
    db: Session, account_id: int, *, format: str = "json"
) -> tuple[dict[str, Any], Opened]:
    from app.accounts.playwright_session import playwright_state_path

    account = _account(db, account_id)
    fmt = _file_format(format)
    path = playwright_state_path(account.username)
    if not path.exists():
        raise ToolError(
            "Playwright state.json не найден — импортируйте cookies или сохраните сессию в браузере"
        )
    opened = _download_open(account, "playwright", fmt)
    return (
        {
            "username": account.username,
            "скачивается": "в браузере",
            "download": "playwright",
            "format": fmt,
            "api": f"/api/accounts/{account.username}/playwright-state",
        },
        opened,
    )


def _parse_json_payload(*, data: Any = None, path: str | None = None) -> Any:
    if path:
        raw = read_project_file(path)["text"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError("некорректный JSON") from exc
    if data is None:
        raise ToolError("нужен JSON data или path к файлу в проекте")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise ToolError("некорректный JSON") from exc
    if isinstance(data, (dict, list)):
        return data
    raise ToolError("нужен JSON data или path к файлу в проекте")


def import_cookies(
    db: Session,
    account_id: int,
    *,
    data: Any = None,
    path: str | None = None,
) -> dict[str, Any]:
    from app.accounts.cookie_formats import CookieFormatError, import_cookies_data

    if data is None and not path:
        return {
            "ask": True,
            "questions": ["JSON cookies (Dolphin или Playwright state) или путь к файлу в проекте?"],
            "why": "чтобы импортировать сессию",
        }
    account = _account(db, account_id)
    parsed = _parse_json_payload(data=data, path=path)
    try:
        result = import_cookies_data(
            account.username,
            parsed,
            platform=_status_value(account.platform) or "instagram",
        )
    except CookieFormatError as exc:
        raise ToolError(str(exc)) from exc
    if result.session_id:
        account.session_id = result.session_id
    db.commit()
    return {
        "username": account.username,
        "format": result.format,
        "session_id": result.session_id,
        "session_id_imported": bool(result.session_id),
        "playwright_state_saved": result.playwright_state_saved,
    }


def import_fingerprint(
    db: Session,
    account_id: int,
    *,
    data: Any = None,
    path: str | None = None,
) -> dict[str, Any]:
    from app.accounts.device_factory import DeviceFingerprint, save_fingerprint

    if data is None and not path:
        return {
            "ask": True,
            "questions": ["JSON fingerprint или путь к файлу device_*.json в проекте?"],
            "why": "чтобы импортировать цифровой отпечаток",
        }
    account = _account(db, account_id)
    _require_instagram(account, "fingerprint")
    parsed = _parse_json_payload(data=data, path=path)
    if not isinstance(parsed, dict):
        raise ToolError("ожидается JSON-объект fingerprint")
    try:
        fp = DeviceFingerprint.from_dict(parsed)
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError(f"некорректный fingerprint: {exc}") from exc
    saved = save_fingerprint(account.username, fp)
    return {
        "username": account.username,
        "saved": True,
        "path": str(saved),
    }


def get_session(db: Session, account_id: int) -> dict[str, Any]:
    from app.accounts.cookie_formats import STUDIO_PLATFORMS, studio_session_ready
    from app.accounts.playwright_session import cookie_names_from_playwright_state
    from app.accounts.session_export import export_sessionid

    account = _account(db, account_id)
    platform = _account_platform(account)
    if platform in STUDIO_PLATFORMS:
        if not studio_session_ready(account.username, platform):
            raise ToolError(
                "Playwright state не найден — импортируйте cookies или сохраните сессию в браузере"
            )
        names = cookie_names_from_playwright_state(account.username)
        return {
            "username": account.username,
            "platform": platform,
            "playwright_state": True,
            "cookies": len(names),
            "names": names,
        }
    exported = export_sessionid(account.username, db_session_id=account.session_id)
    if exported is None:
        raise ToolError("Сессия не найдена — импортируйте cookies или войдите в аккаунт")
    return {
        "username": account.username,
        "platform": platform,
        "session_id": exported.session_id,
        "source": exported.source,
        "session_file_exists": exported.session_file_exists,
    }


def test_proxies(db: Session, labels: Any = None) -> dict[str, Any]:
    from app.proxies.pool import health_check_record

    if isinstance(labels, str):
        labels = [labels]
    if labels:
        if not isinstance(labels, list):
            raise ToolError("labels должен быть списком меток")
        proxies: list[Proxy] = []
        failed: list[dict[str, Any]] = []
        for label in labels:
            try:
                proxies.append(_proxy_by_label(db, str(label)))
            except ToolError as exc:
                failed.append({"label": str(label), "ok": False, "ошибка": str(exc)})
    else:
        proxies = list(db.scalars(select(Proxy)).all())
        failed = []
    checked: list[dict[str, Any]] = []
    for proxy in proxies:
        ok, snapshot, err = health_check_record(db, proxy)
        row = {
            "label": proxy.label,
            "ok": ok,
            "error": err,
            "ip": snapshot.ip if snapshot else None,
            "country": snapshot.country if snapshot else None,
            **_geo_fields(proxy, snapshot),
        }
        if ok:
            checked.append(row)
        else:
            failed.append({**row, "ошибка": err})
    return {"checked": checked, "failed": failed}


def test_connections(
    db: Session,
    account_ids: Any = None,
    *,
    probe_mobile: bool = False,
) -> dict[str, Any]:
    if account_ids:
        if not isinstance(account_ids, list):
            raise ToolError("account_ids должен быть списком")
        accounts = [_account(db, int(i)) for i in account_ids]
    else:
        accounts = list(db.scalars(select(Account).where(Account.proxy_id.isnot(None))).all())
    if not accounts:
        return {"checked": [], "failed": [], "ошибка": "нет аккаунтов с прокси"}
    checked: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for account in accounts:
        try:
            row = test_connection(db, account.id, probe_mobile=probe_mobile)
        except ToolError as exc:
            row = {
                "username": account.username,
                "platform": _account_platform(account),
                "ok": False,
                "error": str(exc),
            }
        if row.get("ok"):
            checked.append(row)
        else:
            failed.append(row)
    return {"checked": checked, "failed": failed}


def publish_now(
    db: Session,
    account_id: int,
    *,
    filename: str | None = None,
    asset_id: int | None = None,
    title: str = "",
    caption: str | None = None,
    caption_template: str | None = None,
    description: str | None = None,
    tags: str | None = None,
    post_type: str | None = None,
    when: Any = None,
) -> dict[str, Any]:
    from app.scheduler.heartbeat import worker_status
    from app.services import worker_control

    if not filename and asset_id is None:
        return {
            "ask": True,
            "questions": ["какой ролик из библиотеки (filename или asset_id)?"],
            "why": "чтобы опубликовать сейчас",
        }
    connection = test_connection(db, account_id)
    if not connection.get("ok"):
        return {
            "опубликовано": False,
            "проверка": connection,
            "ошибка": connection.get("error") or "подключение не прошло",
        }
    queued = enqueue_publish(
        db,
        account_id=account_id,
        filename=filename,
        asset_id=asset_id,
        title=title,
        caption=caption,
        caption_template=caption_template,
        description=description,
        tags=tags,
        post_type=post_type,
        when=when,
    )
    approved = False
    if queued.get("status") == PostJobStatus.awaiting_review.value:
        approved_job = approve_job(db, int(queued["job_id"]))
        queued = {**queued, "status": approved_job["status"]}
        approved = True
    beat = worker_status(db)
    ours = worker_control.status()
    running = ours.alive or (beat.known and not beat.stale)
    return {
        "опубликовано": True,
        "job": queued,
        "approved": approved,
        "проверка": connection,
        "воркер": running,
        "note": None if running else "очередь стоит, воркер не запущен",
    }


def first_login(db: Session, account_id: int, *, login_surface: str | None = None) -> dict[str, Any]:
    from app.accounts.first_login_service import run_account_first_login

    account = _account(db, account_id)
    _require_instagram(account, "first_login")
    out = run_account_first_login(account, db, surface=login_surface)
    return {
        "username": account.username,
        "ok": out.ok,
        "error": out.error,
        "run_id": out.run_id,
        "challenge": out.challenge,
        "session_imported": out.session_imported,
    }


def mint_mobile_session(db: Session, account_id: int) -> dict[str, Any]:
    from app.accounts.mint_mobile_session import mint_mobile_session as mint

    account = _account(db, account_id)
    _require_instagram(account, "mint_mobile_session")
    out = mint(account, db)
    return {
        "username": account.username,
        "ok": out.ok,
        "error": out.error,
        "run_id": out.run_id,
        "challenge": out.challenge,
        "session_id": out.session_id,
    }


def cancel_render(db: Session, job_id: int, *, confirm: Any = False) -> dict[str, Any]:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise ToolError(f"рендера {job_id} нет")
    if not _confirmed(confirm):
        return _need_confirm(
            f"Отменить рендер {job.id}?",
            "отмена только для задач в очереди",
        )
    if job.status is not PipelineStatus.queued:
        raise ToolError(f"задачу в состоянии «{job.status.value}» отменить нельзя")
    job.status = PipelineStatus.cancelled
    db.commit()
    return {"id": job.id, "status": "cancelled"}


def retry_render(db: Session, job_id: int) -> dict[str, Any]:
    from app.generation.registry import get_backend
    from app.services.retry import NotRetriable, revive

    job = db.get(GenerationJob, job_id)
    if job is None:
        raise ToolError(f"рендера {job_id} нет")
    backend = get_backend(job.backend)
    if not backend.healthcheck():
        raise ToolError(backend.health_detail())
    try:
        revive(job)
    except NotRetriable as exc:
        raise ToolError(str(exc)) from exc
    db.commit()
    return {"id": job.id, "status": _status_value(job.status)}


def list_render_backends() -> list[dict[str, Any]]:
    from app.generation.registry import describe_backends

    return describe_backends()


def create_render(
    db: Session,
    *,
    prompt: str | None = None,
    account_id: int | None = None,
    backend: str | None = None,
    duration_s: float | None = None,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
    negative_prompt: str = "",
) -> dict[str, Any]:
    from app.config import get_settings
    from app.generation.registry import available_backends, get_backend

    text = (prompt or "").strip()
    if not text:
        return {
            "ask": True,
            "questions": ["какой промпт для рендера?"],
            "why": "чтобы поставить рендер",
        }
    settings = get_settings()
    if backend is None or str(backend).strip() == "":
        name = (settings.video_backend or "auto").strip().lower()
    else:
        name = one_word(backend)
    if name not in available_backends():
        raise ToolError(f"неизвестный бэкенд {name!r}")
    engine = get_backend(name)
    if not engine.healthcheck():
        raise ToolError(engine.health_detail())
    if account_id is not None:
        _account(db, account_id)
    seconds = 5.0 if duration_s is None else float(duration_s)
    seconds = max(5.0, min(seconds, 10.0))
    job = GenerationJob(
        prompt=text,
        negative_prompt=negative_prompt or "",
        backend=name,
        duration_s=seconds,
        width=720 if width is None else int(width),
        height=1280 if height is None else int(height),
        seed=seed,
        account_id=account_id,
        status=PipelineStatus.queued,
        scheduled_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {
        "id": job.id,
        "status": _status_value(job.status),
        "prompt": job.prompt,
        "backend": job.backend,
    }


def compose(
    db: Session,
    *,
    clip_ids: Any = None,
    audio_asset_id: int | None = None,
    account_id: int | None = None,
    post_title: str = "",
) -> dict[str, Any]:
    ids = _clip_ids(clip_ids)
    if len(ids) < 2:
        return {
            "ask": True,
            "questions": ["какие клипы склеить (минимум два asset_id)?"],
            "why": "чтобы поставить склейку",
        }
    assets = {
        asset.id: asset
        for asset in db.scalars(select(MediaAsset).where(MediaAsset.id.in_(ids))).all()
    }
    missing = [clip_id for clip_id in ids if clip_id not in assets]
    if missing:
        raise ToolError(f"неизвестные клипы: {missing}")
    if account_id is not None:
        _account(db, account_id)
    composition = Composition(
        audio_asset_id=audio_asset_id,
        account_id=account_id,
        post_title=post_title or "",
        status=PipelineStatus.queued,
        scheduled_at=datetime.now(timezone.utc),
    )
    db.add(composition)
    db.flush()
    for index, clip_id in enumerate(ids):
        db.add(CompositionClip(composition_id=composition.id, asset_id=clip_id, position=index))
    db.commit()
    db.refresh(composition)
    return {"id": composition.id, "status": _status_value(composition.status), "clips": len(ids)}


def cancel_composition(db: Session, job_id: int, *, confirm: Any = False) -> dict[str, Any]:
    job = db.get(Composition, job_id)
    if job is None:
        raise ToolError(f"склейки {job_id} нет")
    if not _confirmed(confirm):
        return _need_confirm(
            f"Отменить склейку {job.id}?",
            "отмена только для задач в очереди",
        )
    if job.status is not PipelineStatus.queued:
        raise ToolError(f"задачу в состоянии «{job.status.value}» отменить нельзя")
    job.status = PipelineStatus.cancelled
    db.commit()
    return {"id": job.id, "status": "cancelled"}


def retry_composition(db: Session, job_id: int) -> dict[str, Any]:
    from app.services.retry import NotRetriable, revive

    job = db.get(Composition, job_id)
    if job is None:
        raise ToolError(f"склейки {job_id} нет")
    try:
        revive(job)
    except NotRetriable as exc:
        raise ToolError(str(exc)) from exc
    db.commit()
    return {"id": job.id, "status": _status_value(job.status)}


def check_source(db: Session, source_id: int) -> dict[str, Any]:
    from app.agent.sources import SourceError, read_source
    from app.config import settings as cfg

    row = db.get(ChannelSource, source_id)
    if row is None:
        raise ToolError(f"источника {source_id} нет")
    try:
        read_source(row.kind, row.value, row.label, cfg)
        row.last_status = "ok"
    except SourceError as exc:
        row.last_status = str(exc)[:200]
    row.last_read_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": row.id, "last_status": row.last_status}


def refresh_stats(db: Session, publication_id: int) -> dict[str, Any]:
    from app.publications.stats import refresh_post_log_stats

    row = db.get(PostLog, publication_id)
    if row is None:
        raise ToolError(f"публикации {publication_id} нет")
    try:
        row = refresh_post_log_stats(db, row)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        raise ToolError(f"Stats refresh failed: {exc}") from exc
    return {
        "id": row.id,
        "job_id": row.job_id,
        "success": row.success,
        "view_count": row.view_count,
        "like_count": row.like_count,
        "last_stats_at": _when(row.last_stats_at),
        "error": row.error,
    }


def start_browser(
    db: Session,
    *,
    account_id: int | None = None,
    username: str | None = None,
    login_surface: str | None = None,
) -> dict[str, Any]:
    from app.browser.session_manager import browser_session_manager

    account = _account_lookup(db, account_id=account_id, username=username)
    if account.proxy_id is None:
        raise ToolError("Прокси не назначен")
    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        raise ToolError("Запись прокси отсутствует")
    from app.behavior.playwright_surface import resolve_playwright_surface

    resolved = resolve_playwright_surface(login_surface or account.login_surface)
    account.login_surface = resolved
    db.commit()
    try:
        _run_async(
            browser_session_manager.start_session(
                account,
                proxy,
                surface=resolved,
                proxy_snapshot=None,
            )
        )
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    status = browser_session_manager.status_dict(account.username)
    return {
        "username": account.username,
        "platform": _account_platform(account),
        "status": status.get("status"),
        "awaiting_code": status.get("awaiting_code"),
        "page_url": status.get("page_url"),
        "error": status.get("error"),
        "vnc_path": status.get("vnc_path"),
    }


def browser_status(
    db: Session,
    *,
    account_id: int | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    from app.browser.session_manager import browser_session_manager

    account = _account_lookup(db, account_id=account_id, username=username)
    status = browser_session_manager.status_dict(account.username)
    return {
        "username": account.username,
        "platform": _account_platform(account),
        "status": status.get("status"),
        "awaiting_code": status.get("awaiting_code"),
        "page_url": status.get("page_url"),
        "error": status.get("error"),
        "vnc_path": status.get("vnc_path"),
    }


def save_browser_session(
    db: Session,
    *,
    account_id: int | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    from app.browser.session_manager import browser_session_manager

    account = _account_lookup(db, account_id=account_id, username=username)
    try:
        result = _run_async(browser_session_manager.save_session(db, account))
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    db.refresh(account)
    status = browser_session_manager.status_dict(account.username)
    return {
        "username": account.username,
        "platform": _account_platform(account),
        **result,
        "session_id": account.session_id,
        "status": status.get("status"),
    }


def submit_browser_code(
    db: Session,
    *,
    code: str | None = None,
    account_id: int | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    from app.browser.session_manager import browser_session_manager

    text = (code or "").strip()
    if not text:
        return {
            "ask": True,
            "questions": ["какой код из письма/приложения (2FA)?"],
            "why": "чтобы подтвердить вход в живом браузере",
        }
    account = _account_lookup(db, account_id=account_id, username=username)
    try:
        _run_async(browser_session_manager.submit_code(db, account, text))
    except (ValueError, RuntimeError) as exc:
        raise ToolError(str(exc)) from exc
    status = browser_session_manager.status_dict(account.username)
    return {
        "username": account.username,
        "status": status.get("status"),
        "awaiting_code": status.get("awaiting_code"),
        "page_url": status.get("page_url"),
    }


def wait_render(
    db: Session,
    job_id: int,
    *,
    timeout_s: float = 300.0,
    poll_s: float = 2.0,
) -> dict[str, Any]:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise ToolError(f"рендера {job_id} нет")
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    interval = max(0.05, float(poll_s))
    terminal = {
        PipelineStatus.done,
        PipelineStatus.failed,
        PipelineStatus.dead,
        PipelineStatus.cancelled,
    }
    while True:
        db.refresh(job)
        if job.status in terminal:
            return {
                "id": job.id,
                "status": _status_value(job.status),
                "asset_id": job.asset_id,
                "last_error": job.last_error,
            }
        if time.monotonic() >= deadline:
            raise ToolError(f"рендер {job_id} ещё «{job.status.value}» — не дождался")
        time.sleep(interval)


def wait_plan(
    db: Session,
    plan_id: int,
    *,
    timeout_s: float = 300.0,
    poll_s: float = 2.0,
) -> dict[str, Any]:
    job = db.get(PlanJob, plan_id)
    if job is None:
        raise ToolError(f"плана {plan_id} нет")
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    interval = max(0.05, float(poll_s))
    terminal = {
        PipelineStatus.done,
        PipelineStatus.failed,
        PipelineStatus.dead,
        PipelineStatus.cancelled,
    }
    while True:
        db.refresh(job)
        if job.status in terminal:
            gens = db.scalars(
                select(GenerationJob.id).where(GenerationJob.plan_job_id == job.id)
            ).all()
            return {
                "id": job.id,
                "status": _status_value(job.status),
                "planned": job.planned,
                "generation_ids": list(gens),
                "last_error": job.last_error,
            }
        if time.monotonic() >= deadline:
            raise ToolError(f"план {plan_id} ещё «{job.status.value}» — не дождался")
        time.sleep(interval)


def answer_question(db: Session, question_id: int, answer: str) -> dict[str, Any]:
    row = db.get(Clarification, question_id)
    if row is None:
        raise ToolError(f"вопроса {question_id} нет")
    if not (answer or "").strip():
        raise ToolError("ответ не может быть пустым")
    saved = answer_clarification(db, row, answer, by="assistant")
    return {"id": saved.id, "question": saved.question, "answer": saved.answer}


def add_source(db: Session, account_id: int, value: str, *, kind: str = "url") -> dict[str, Any]:
    account = _account(db, account_id)
    try:
        source_kind = SourceKind(one_word(kind) or "url")
    except ValueError as exc:
        raise ToolError("kind должен быть url или file") from exc
    row = ChannelSource(
        account_id=account.id,
        kind=source_kind,
        value=value.strip(),
        label="",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "kind": source_kind.value, "value": row.value}


def list_questions(db: Session, *, account_id: int | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(Clarification)
        .where(Clarification.answer.is_(None), Clarification.dismissed.is_(False))
        .order_by(Clarification.asked_at.desc())
        .limit(LIMIT)
    )
    if account_id is not None:
        stmt = stmt.where(Clarification.account_id == account_id)
    names = _account_names(db)
    return [
        {
            "id": r.id,
            "question": r.question,
            "why": r.why,
            "assumed": r.assumed,
            "open": r.open,
            "account_id": r.account_id,
            "account": names.get(r.account_id, f"#{r.account_id}"),
        }
        for r in db.scalars(stmt).all()
    ]


def list_sources(db: Session, account_id: int) -> list[dict[str, Any]]:
    account = _account(db, account_id)
    rows = db.scalars(select(ChannelSource).where(ChannelSource.account_id == account.id)).all()
    return [
        {
            "id": r.id,
            "kind": r.kind.value if hasattr(r.kind, "value") else r.kind,
            "value": r.value,
            "label": r.label,
            "enabled": r.enabled,
            "last_status": r.last_status,
        }
        for r in rows
    ]


def list_presets(db: Session) -> list[dict[str, Any]]:
    from app.agent.presets import seed_if_empty

    seed_if_empty(db)
    rows = db.scalars(select(PromptPreset)).all()
    return [{"id": r.id, "name": r.name, "brief": r.brief} for r in rows]


def list_plans(db: Session, *, account_id: int | None = None) -> list[dict[str, Any]]:
    stmt = select(PlanJob).order_by(PlanJob.created_at.desc()).limit(LIMIT)
    if account_id is not None:
        stmt = stmt.where(PlanJob.account_id == account_id)
    names = _account_names(db)
    return [
        {
            "id": r.id,
            "status": _status_value(r.status),
            "count": r.count,
            "planned": r.planned,
            "auto_schedule": bool(r.auto_schedule),
            "spread_over_days": r.spread_over_days,
            "week": r.spread_over_days == 7,
            "last_error": r.last_error,
            "account": names.get(r.account_id, f"#{r.account_id}"),
        }
        for r in db.scalars(stmt).all()
    ]


def apply_preset(db: Session, account_id: int, name: str) -> dict[str, Any]:
    from app.agent.presets import seed_if_empty

    seed_if_empty(db)
    want = (name or "").strip()
    if not want:
        raise ToolError("нужно имя пресета")
    rows = list(db.scalars(select(PromptPreset)).all())
    match = next((r for r in rows if r.name.lower() == want.lower()), None)
    if match is None:
        names = ", ".join(r.name for r in rows) or "нет"
        raise ToolError(f"пресета {want!r} нет; есть: {names}")
    account = _account(db, account_id)
    account.brief = match.brief
    db.commit()
    return {"account": account.username, "preset": match.name, "brief": account.brief}


def create_proxy(
    db: Session,
    *,
    label: str,
    url: str,
    country: str | None = None,
    timezone: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    from app.proxies.pool import upsert_proxy

    if not (label or "").strip() or not (url or "").strip():
        raise ToolError("нужны label и url прокси")
    proxy = upsert_proxy(
        db,
        label=label.strip(),
        url=url.strip(),
        country=country,
        timezone_name=timezone,
        notes=notes,
    )
    return {
        "id": proxy.id,
        "label": proxy.label,
        "url": proxy.url,
        "country": proxy.country,
    }


def update_proxy(
    db: Session,
    label: str,
    *,
    url: str | None = None,
    country: str | None = None,
    timezone: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    from app.proxies.pool import upsert_proxy

    existing = _proxy_by_label(db, label)
    proxy = upsert_proxy(
        db,
        label=existing.label,
        url=(url or existing.url).strip(),
        country=country,
        timezone_name=timezone,
        notes=notes,
    )
    return {
        "id": proxy.id,
        "label": proxy.label,
        "url": proxy.url,
        "country": proxy.country,
    }


def attach_proxy(db: Session, account_id: int, proxy_label: str) -> dict[str, Any]:
    from app.geo.timezone_normalize import timezone_from_proxy

    account = _account(db, account_id)
    proxy = _proxy_by_label(db, proxy_label)
    account.proxy_id = proxy.id
    account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
    db.commit()
    return {
        "id": account.id,
        "username": account.username,
        "proxy_label": proxy.label,
        "proxy_url": proxy.url,
    }


def create_account(
    db: Session,
    *,
    username: str,
    proxy_label: str,
    password: str = "",
    platform: str = "instagram",
    totp_seed: str | None = None,
    session_id: str | None = None,
    email: str | None = None,
    email_password: str | None = None,
    brief: str | None = None,
    notes: str | None = None,
    account_line: str | None = None,
    login_identifier: str | None = None,
    backup_codes: str | None = None,
) -> dict[str, Any]:
    return _upsert_account(
        db,
        username=username,
        proxy_label=proxy_label,
        password=password,
        platform=platform,
        totp_seed=totp_seed,
        session_id=session_id,
        email=email,
        email_password=email_password,
        brief=brief,
        notes=notes,
        account_line=account_line,
        login_identifier=login_identifier,
        backup_codes=backup_codes,
        creating=True,
    )


BULK_LIMIT = 20


def _bulk_items(raw: Any) -> list[Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError("items должен быть JSON-массивом") from exc
    if not isinstance(raw, list):
        raise ToolError("нужен JSON-массив items")
    if len(raw) > BULK_LIMIT:
        raise ToolError(f"не больше {BULK_LIMIT} за раз")
    if not raw:
        raise ToolError("пустой список")
    return raw


def _item_text(item: dict[str, Any], key: str) -> str | None:
    if key not in item or item.get(key) in (None, ""):
        return None
    text = str(item.get(key)).strip()
    return text or None


def create_accounts(db: Session, items: Any) -> dict[str, Any]:
    rows = _bulk_items(items)
    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    incomplete = 0
    for item in rows:
        if not isinstance(item, dict):
            failed.append({"item": item, "ошибка": "не объект"})
            continue
        username = str(item.get("username") or "").strip()
        proxy_label = str(item.get("proxy_label") or "").strip()
        if not username or not proxy_label:
            incomplete += 1
            failed.append(
                {
                    "item": item.get("username") or item,
                    "ошибка": "нужны username и proxy_label",
                }
            )
            continue
        try:
            created.append(
                create_account(
                    db,
                    username=username,
                    proxy_label=proxy_label,
                    password=str(item.get("password") or ""),
                    platform=str(item.get("platform") or "instagram"),
                    totp_seed=_item_text(item, "totp_seed"),
                    session_id=_item_text(item, "session_id"),
                    email=_item_text(item, "email"),
                    email_password=_item_text(item, "email_password"),
                    brief=_item_text(item, "brief"),
                    notes=_item_text(item, "notes"),
                    account_line=_item_text(item, "account_line"),
                    login_identifier=_item_text(item, "login_identifier"),
                    backup_codes=_item_text(item, "backup_codes"),
                )
            )
        except ToolError as exc:
            failed.append({"item": username, "ошибка": str(exc)})
    if not created and incomplete == len(rows):
        return {
            "ask": True,
            "questions": [
                "username каждого аккаунта?",
                "proxy_label существующего прокси?",
            ],
            "why": "чтобы добавить аккаунты",
        }
    return {"created": created, "failed": failed}


def create_proxies(db: Session, items: Any) -> dict[str, Any]:
    rows = _bulk_items(items)
    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    incomplete = 0
    for item in rows:
        if not isinstance(item, dict):
            failed.append({"item": item, "ошибка": "не объект"})
            continue
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not label or not url:
            incomplete += 1
            failed.append({"item": item.get("label") or item, "ошибка": "нужны label и url"})
            continue
        try:
            created.append(
                create_proxy(
                    db,
                    label=label,
                    url=url,
                    country=_item_text(item, "country"),
                    timezone=_item_text(item, "timezone"),
                    notes=_item_text(item, "notes"),
                )
            )
        except ToolError as exc:
            failed.append({"item": label, "ошибка": str(exc)})
    if not created and incomplete == len(rows):
        return {
            "ask": True,
            "questions": [
                "метка каждого прокси?",
                "url каждого прокси (http://user:pass@host:port)?",
            ],
            "why": "чтобы добавить прокси",
        }
    return {"created": created, "failed": failed}


def update_account(
    db: Session,
    account_id: int,
    *,
    password: str | None = None,
    totp_seed: str | None = None,
    session_id: str | None = None,
    email: str | None = None,
    email_password: str | None = None,
    brief: str | None = None,
    notes: str | None = None,
    proxy_label: str | None = None,
    login_identifier: str | None = None,
    backup_codes: str | None = None,
    username: str | None = None,
    daily_post_cap: int | None = None,
    min_gap_hours: float | None = None,
    active_hour_start: int | None = None,
    active_hour_end: int | None = None,
    timezone: str | None = None,
    caption_profile: str | None = None,
    hold_for_review: bool | None = None,
    login_surface: str | None = None,
) -> dict[str, Any]:
    account = _account(db, account_id)
    if username is not None and username.strip():
        account.username = username.strip()
    if password is not None:
        account.password = password
    if totp_seed is not None:
        account.totp_seed = totp_seed.strip() or None
    if session_id is not None:
        _require_instagram(account, "session_id")
        from app.accounts.session_cookie import normalize_sessionid
        from app.accounts.session_manager import clear_session_file
        from app.accounts.playwright_session import clear_playwright_state

        account.session_id = normalize_sessionid(session_id)
        if account.session_id:
            clear_session_file(account.username)
            clear_playwright_state(account.username)
    if email is not None:
        account.email = email or None
    if email_password is not None:
        account.email_password = email_password or None
    if brief is not None:
        account.brief = brief
    if notes is not None:
        account.notes = notes.strip() or None
    if login_identifier is not None:
        account.login_identifier = login_identifier.strip() or None
    if backup_codes is not None:
        account.backup_codes = backup_codes.strip() or None
    if proxy_label:
        proxy = _proxy_by_label(db, proxy_label)
        account.proxy_id = proxy.id
    if daily_post_cap is not None:
        account.daily_post_cap = max(1, min(int(daily_post_cap), 20))
    if min_gap_hours is not None:
        account.min_gap_hours = max(0.5, min(float(min_gap_hours), 24.0))
    start = account.active_hour_start if active_hour_start is None else max(0, min(int(active_hour_start), 23))
    end = account.active_hour_end if active_hour_end is None else max(1, min(int(active_hour_end), 23))
    if end <= start:
        raise ToolError("active_hour_end должен быть больше active_hour_start")
    if active_hour_start is not None:
        account.active_hour_start = start
    if active_hour_end is not None:
        account.active_hour_end = end
    if timezone is not None and timezone.strip():
        account.timezone = timezone.strip()
    if caption_profile is not None:
        profile = caption_profile.strip().lower()
        if not profile:
            account.caption_profile = None
        elif profile not in _CAPTION_PROFILES:
            allowed = ", ".join(sorted(_CAPTION_PROFILES))
            raise ToolError(f"caption_profile должен быть одним из: {allowed}")
        else:
            account.caption_profile = profile
    if hold_for_review is not None:
        account.hold_for_review = bool(hold_for_review)
    if login_surface is not None:
        from app.behavior.playwright_surface import resolve_playwright_surface

        account.login_surface = resolve_playwright_surface(login_surface)
    db.commit()
    db.refresh(account)
    return account_details(db, account.id)


def _upsert_account(
    db: Session,
    *,
    username: str,
    proxy_label: str,
    password: str = "",
    platform: str = "instagram",
    totp_seed: str | None = None,
    session_id: str | None = None,
    email: str | None = None,
    email_password: str | None = None,
    brief: str | None = None,
    notes: str | None = None,
    account_line: str | None = None,
    login_identifier: str | None = None,
    backup_codes: str | None = None,
    creating: bool = False,
) -> dict[str, Any]:
    from app.accounts.backup_codes import parse_account_line, serialize_backup_codes
    from app.accounts.session_cookie import normalize_sessionid
    from app.accounts.session_manager import clear_session_file, ensure_fingerprint_and_proxy
    from app.accounts.playwright_session import clear_playwright_state
    from app.geo.country_codes import normalize_country_code
    from app.geo.timezone_normalize import timezone_from_proxy

    proxy = _proxy_by_label(db, proxy_label)
    kind = _platform(platform)
    name = (username or "").strip()
    if account_line:
        try:
            parsed = parse_account_line(account_line)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        name = parsed["username"]
        password = parsed["password"]
        codes = parsed.get("backup_codes") or []
        if codes:
            backup_codes = serialize_backup_codes(codes)
    if not name:
        raise ToolError("нужен username")
    existing = db.scalar(select(Account).where(Account.username == name, Account.platform == kind))
    if existing is None:
        account = Account(username=name, platform=kind)
        db.add(account)
    else:
        if creating:
            account = existing
        else:
            account = existing
    account.platform = kind
    account.password = password or account.password
    account.proxy_id = proxy.id
    account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
    if totp_seed is not None:
        account.totp_seed = totp_seed.strip() or None
    if session_id is not None:
        if kind.value != "instagram":
            raise ToolError("session_id только для Instagram — YouTube и TikTok входят через cookies / браузер в UI")
        account.session_id = normalize_sessionid(session_id)
        if account.session_id:
            clear_session_file(account.username)
            clear_playwright_state(account.username)
    if email is not None:
        account.email = email or None
    if email_password is not None:
        account.email_password = email_password or None
    if brief is not None:
        account.brief = brief
    if notes is not None:
        account.notes = notes.strip() or None
    if login_identifier is not None:
        account.login_identifier = login_identifier.strip() or None
    if backup_codes is not None:
        account.backup_codes = backup_codes.strip() or None
    if account.status == AccountStatus.blocked:
        account.status = AccountStatus.active
    db.commit()
    db.refresh(account)
    if kind.value == "instagram":
        try:
            ensure_fingerprint_and_proxy(
                account.username,
                country=normalize_country_code(proxy.country) or proxy.country or "US",
                timezone_id=timezone_from_proxy(proxy.timezone, proxy.country),
            )
        except OSError:
            pass
    return account_details(db, account.id)


def _account_public(account: Account) -> dict[str, Any]:
    proxy = account.proxy
    return {
        "id": account.id,
        "username": account.username,
        "password": account.password,
        "platform": _status_value(account.platform),
        "status": _status_value(account.status),
        "brief": account.brief,
        "posts_per_day": account.daily_post_cap,
        "holds_for_review": bool(account.hold_for_review),
        "totp_seed": account.totp_seed,
        "session_id": account.session_id,
        "proxy_label": proxy.label if proxy is not None else None,
        "proxy_url": proxy.url if proxy is not None else None,
    }


def _account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise ToolError(f"аккаунта {account_id} нет")
    return account


def _account_lookup(
    db: Session,
    *,
    account_id: int | None = None,
    username: str | None = None,
) -> Account:
    if account_id is not None:
        return _account(db, account_id)
    name = (username or "").strip()
    if not name:
        raise ToolError("нужен account_id или username")
    rows = db.scalars(select(Account).where(Account.username == name)).all()
    if not rows:
        raise ToolError(f"аккаунта {name!r} нет")
    if len(rows) > 1:
        raise ToolError(f"несколько аккаунтов с именем {name!r} — укажи account_id")
    return rows[0]


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _account_names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Account.id, Account.username)).all())


def _proxy_by_label(db: Session, label: str) -> Proxy:
    row = db.scalar(select(Proxy).where(Proxy.label == (label or "").strip()))
    if row is None:
        raise ToolError(f"прокси {label!r} нет")
    return row


def _platform(raw: Any) -> Platform:
    word = one_word(raw) or "instagram"
    try:
        return Platform(word)
    except ValueError:
        raise ToolError(
            f"площадки {word!r} нет; площадки такие: {', '.join(p.value for p in Platform)}"
        ) from None


def _allowed_roots() -> list[Path]:
    from app.config import settings as cfg

    roots = [PROJECT_ROOT.resolve()]
    data = Path(cfg.data_dir).resolve()
    if data not in roots:
        roots.append(data)
    return roots


def _inside_project(raw: str) -> Path:
    relative = (raw or ".").replace("\\", "/").strip() or "."
    if Path(relative).is_absolute():
        candidate = Path(relative).resolve()
    else:
        candidate = (PROJECT_ROOT / relative).resolve()
    for root in _allowed_roots():
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise ToolError("путь должен быть внутри проекта")


def _rel_to_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def one_word(raw: Any) -> str:
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    return str(raw).strip().lower()


def _post_status(raw: Any) -> PostJobStatus:
    word = one_word(raw)
    try:
        return PostJobStatus(word)
    except ValueError:
        raise ToolError(
            f"статуса {word!r} нет; статусы такие: {', '.join(s.value for s in PostJobStatus)}"
        ) from None


def _pipeline_status(raw: Any) -> PipelineStatus:
    word = one_word(raw)
    try:
        return PipelineStatus(word)
    except ValueError:
        raise ToolError(
            f"статуса {word!r} нет; статусы такие: {', '.join(s.value for s in PipelineStatus)}"
        ) from None


_CAPTION_PROFILES = {"nature", "lifestyle", "fitness", "food", "travel"}


def _parse_when(raw: Any) -> datetime | None:
    if raw in (None, "", [], False):
        return None
    if isinstance(raw, datetime):
        when = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def _parse_post_type(raw: Any) -> PostType:
    word = one_word(raw)
    try:
        return PostType(word)
    except ValueError:
        raise ToolError(
            f"типа {word!r} нет; типы такие: {', '.join(t.value for t in PostType)}"
        ) from None


def _clip_ids(raw: Any) -> list[int]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    if not isinstance(raw, list | tuple):
        raw = [raw]
    ids: list[int] = []
    for item in raw:
        try:
            ids.append(int(str(item).strip()))
        except (TypeError, ValueError) as exc:
            raise ToolError(f"clip_ids должен быть списком id, а пришло {raw!r}") from exc
    return ids


def _kind(raw: Any) -> AssetKind:
    word = one_word(raw)
    try:
        return AssetKind(word)
    except ValueError:
        raise ToolError("вида нет; клип — 'video', саундтрек — 'audio'") from None
