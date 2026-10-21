"""Stop a running Salad GPU group after the panel goes quiet.

Salad's webhook secret does not report chat idle and cannot warm Ollama.
Warmup is a container command (see docker/salad-gpu/README.md). This loop
only calls the public Start/Stop API the admin card already uses.

The idle clock is the later of "the group became running" and the last
bottom-chat or local-render touch. A fresh Start therefore gets a full
window before the first message. ``data/gpu_slot.lock``, queued/running
local/auto/chain renders, and live panel presence heartbeats block the stop.
While busy, ``touch`` advances ``last_used`` so the idle window restarts
after work ends.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import GenerationJob, PipelineStatus
from app.logging_setup import get_logger
from app.services import salad_gpu
from app.services.gpu_slot import video_busy

log = get_logger(__name__)

ACTIVITY_NAME = "gpu_activity.json"
POLL_SECONDS = 60
PRESENCE_TTL = timedelta(seconds=120)
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,80}$")


def _path(settings: Settings) -> Path:
    return Path(settings.data_dir) / ACTIVITY_NAME


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _load_raw(settings: Settings) -> dict[str, Any]:
    path = _path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _load(settings: Settings) -> dict[str, str]:
    raw = _load_raw(settings)
    out: dict[str, str] = {}
    for key in ("last_used", "running_since"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _viewers(raw: dict[str, Any]) -> dict[str, str]:
    blob = raw.get("viewers")
    if not isinstance(blob, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in blob.items():
        if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
            out[key.strip()] = value.strip()
    return out


def _save_activity(settings: Settings, *, marks: dict[str, str], viewers: dict[str, str]) -> None:
    path = _path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {k: v for k, v in marks.items() if v}
    if viewers:
        payload["viewers"] = viewers
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _save(settings: Settings, data: dict[str, str]) -> None:
    raw = _load_raw(settings)
    _save_activity(settings, marks=data, viewers=_viewers(raw))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def touch(settings: Settings | None = None, *, now: datetime | None = None) -> None:
    """Remember that chat or a local render just used the GPU."""
    settings = settings or get_settings()
    data = _load(settings)
    data["last_used"] = _now(now).isoformat()
    _save(settings, data)


def touch_presence(
    client_id: str,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Record a panel tab heartbeat. Returns how many viewers are still alive."""
    settings = settings or get_settings()
    cid = (client_id or "").strip()
    if not _CLIENT_ID_RE.match(cid):
        raise ValueError("Некорректный client_id для presence")
    current = _now(now)
    raw = _load_raw(settings)
    marks = _load(settings)
    viewers = _viewers(raw)
    viewers[cid] = current.isoformat()
    viewers = _prune_viewers(viewers, now=current)
    _save_activity(settings, marks=marks, viewers=viewers)
    return len(viewers)


def _prune_viewers(viewers: dict[str, str], *, now: datetime) -> dict[str, str]:
    alive: dict[str, str] = {}
    for cid, stamp in viewers.items():
        seen = _parse(stamp)
        if seen is not None and now - seen <= PRESENCE_TTL:
            alive[cid] = stamp
    return alive


def presence_alive(settings: Settings | None = None, *, now: datetime | None = None) -> bool:
    """True when at least one panel tab pinged within PRESENCE_TTL."""
    settings = settings or get_settings()
    current = _now(now)
    raw = _load_raw(settings)
    viewers = _prune_viewers(_viewers(raw), now=current)
    marks = _load(settings)
    if viewers != _viewers(raw):
        _save_activity(settings, marks=marks, viewers=viewers)
    return bool(viewers)


def observe_status(
    settings: Settings,
    status: str,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Stamp running_since the first time we see running; clear it otherwise."""
    data = _load(settings)
    if status == "running":
        if not data.get("running_since"):
            data["running_since"] = _now(now).isoformat()
    else:
        data.pop("running_since", None)
    _save(settings, data)
    return data


def _anchor(data: dict[str, str]) -> datetime | None:
    marks = [mark for key in ("last_used", "running_since") if (mark := _parse(data.get(key)))]
    if not marks:
        return None
    return max(marks)


def local_render_pending(db: Session, settings: Settings | None = None) -> bool:
    """Queued/running work that may use the Salad WAN GPU (not fal-only VPS)."""
    settings = settings or get_settings()
    from app.generation.registry import parse_chain

    chain_has_local = "local" in parse_chain(settings)
    rows = db.scalars(
        select(GenerationJob).where(
            GenerationJob.status.in_((PipelineStatus.queued, PipelineStatus.running)),
        )
    ).all()
    for job in rows:
        backend = (job.backend or "auto").strip().lower() or "auto"
        if backend in ("local", "chain"):
            return True
        if backend == "auto" and chain_has_local:
            return True
    return False


def idle_due(
    settings: Settings,
    *,
    status: str,
    busy: bool,
    now: datetime | None = None,
) -> bool:
    minutes = int(settings.salad_idle_stop_minutes)
    if minutes <= 0 or busy or status != "running":
        return False
    anchor = _anchor(_load(settings))
    if anchor is None:
        return False
    return _now(now) - anchor >= timedelta(minutes=minutes)


def tick(settings: Settings | None = None, *, now: datetime | None = None) -> bool:
    """Stop the group when it has been quiet long enough. True if Stop was sent."""
    settings = settings or get_settings()
    if int(settings.salad_idle_stop_minutes) <= 0 or not salad_gpu.configured(settings):
        return False
    try:
        state = salad_gpu.get_group(settings)
    except salad_gpu.SaladProblem:
        log.warning("salad.idle_status_failed")
        return False
    current = _now(now)
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        slot_busy = video_busy(settings) is not None
        render_busy = local_render_pending(db, settings)
        panel_busy = presence_alive(settings, now=current)
        busy = slot_busy or render_busy or panel_busy
    finally:
        db.close()
    observe_status(settings, state.status, now=current)
    if busy:
        touch(settings, now=current)
        return False
    due = idle_due(settings, status=state.status, busy=False, now=current)
    if not due:
        return False
    try:
        salad_gpu.stop_group(settings)
    except salad_gpu.SaladProblem:
        log.warning("salad.idle_stop_failed")
        return False
    log.info("salad.idle_stop", minutes=int(settings.salad_idle_stop_minutes))
    return True
