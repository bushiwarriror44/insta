"""Turning a queued composition into a finished clip.

Encoding is real work — a minute of 1080x1920 is not instant — so this is
a job the worker claims rather than something an HTTP request waits on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import (
    MediaAsset,
    AssetKind,
    AssetSource,
    Composition,
    Event,
    EventLevel,
    PipelineStatus,
)
from app.scheduler.queue import claim_due, fail
from app.services.media import MediaError, asset_media_path, probe_video
from app.video.compose import ComposeError, ComposeRequest, compose

MAX_ATTEMPTS = 3


def claim_due_composition(
    session: Session, *, now: datetime | None = None
) -> Composition | None:
    return claim_due(session, Composition, now=now)


def ensure_composition_media(
    session: Session,
    job: Composition,
    *,
    settings: Settings | None = None,
) -> None:
    """Reject a retry or enqueue when the source clips are gone."""
    settings = settings or get_settings()
    media = Path(settings.media_dir)
    bound = session.get(Composition, job.id)
    if bound is not None:
        job = bound
    if len(job.clips) < 2:
        raise MediaError("склейка: нужны минимум два клипа")
    for clip in job.clips:
        asset_media_path(media, clip.asset)
    if (job.audio_filename or "").strip():
        from app.video.mux_audio import MuxError, resolve_audio_file

        try:
            resolve_audio_file(job.audio_filename, settings)
        except MuxError as exc:
            raise MediaError(str(exc)) from exc
    elif job.audio is not None:
        asset_media_path(media, job.audio)


def run_composition(
    session: Session,
    job: Composition,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> None:
    """Join the clips and file the result as a new asset."""
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    media = Path(settings.media_dir)

    if len(job.clips) < 2:
        _fail(
            session,
            job,
            "склейка: нужны минимум два клипа",
            retryable=False,
            now=now,
        )
        return

    try:
        clip_paths = [asset_media_path(media, clip.asset) for clip in job.clips]
        if (job.audio_filename or "").strip():
            from app.video.mux_audio import MuxError, resolve_audio_file

            try:
                audio_path = resolve_audio_file(job.audio_filename, settings)
            except MuxError as exc:
                raise MediaError(str(exc)) from exc
        else:
            audio_path = asset_media_path(media, job.audio) if job.audio else None
    except MediaError as exc:
        _fail(session, job, str(exc), retryable=False, now=now)
        return

    job.attempts += 1

    output = media / f"{uuid.uuid4().hex}.mp4"
    request = ComposeRequest(
        clips=clip_paths,
        output=output,
        audio=audio_path,
        audio_start_s=float(job.audio_start_s or 0),
        width=job.width,
        height=job.height,
        fps=job.fps,
        audio_fade_out_s=job.audio_fade_out_s,
    )

    try:
        compose(request)
    except ComposeError as exc:
        _fail(session, job, str(exc), retryable=exc.retryable, now=now)
        return

    probe = probe_video(output)
    asset = MediaAsset(
        filename=output.name,
        kind=AssetKind.video,
        source=AssetSource.composed,
        # Whatever made the pieces made this; the platforms ask about the
        # footage, not about the last step that touched it.
        generator=", ".join(
            sorted({clip.asset.generator for clip in job.clips if clip.asset.generator})
        )
        or None,
        prompt=" · ".join(clip.asset.prompt for clip in job.clips if clip.asset.prompt)
        or None,
        duration_s=probe.duration_s,
        width=probe.width or job.width,
        height=probe.height or job.height,
    )
    session.add(asset)
    session.flush()

    job.status = PipelineStatus.done
    job.output_asset_id = asset.id
    job.last_error = None
    job.finished_at = now
    session.add(job)
    session.add(
        Event(
            level=EventLevel.info,
            kind="composed",
            account_id=job.account_id,
            message=(
                f"клипов: {len(job.clips)} → {probe.duration_s or 0:.0f} с"
                f"{' со звуком' if job.audio else ''}"
            ),
        )
    )
    session.commit()

    if job.auto_schedule and job.account_id is not None:
        _schedule_the_post(session, job, asset)


def _schedule_the_post(session: Session, job: Composition, asset: MediaAsset) -> None:
    """Queue the publish this join was planned to become.

    The copy travelled here from the plan, because by the time the clips
    exist the planning run that asked for them has long finished. A
    scheduling failure must not undo renders already paid for, so the
    asset stays and the problem is logged.
    """
    from app.db.models import Account
    from app.services.scheduling import PlanningError, days_ahead_for_plan, schedule_assets

    channel = session.get(Account, job.account_id)
    if channel is None:
        return

    try:
        schedule_assets(
            session,
            channel,
            [asset],
            titles={asset.id: job.post_title} if job.post_title else None,
            description=job.post_description,
            tags=[t.strip() for t in job.post_tags.split(",") if t.strip()],
            days_ahead=days_ahead_for_plan(session, post_group=job.post_group),
        )
    except PlanningError as exc:
        session.add(
            Event(
                level=EventLevel.warn,
                kind="schedule_failed",
                account_id=job.account_id,
                message=f"склеено, но не запланировано: {exc}",
            )
        )
        session.commit()


def _fail(
    session: Session,
    job: Composition,
    message: str,
    *,
    retryable: bool,
    now: datetime | None = None,
) -> None:
    fail(
        session,
        job,
        message,
        kind="compose_failed",
        retryable=retryable,
        max_attempts=MAX_ATTEMPTS,
        account_id=job.account_id,
        now=now,
    )
