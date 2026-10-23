"""Turn a queued prompt into an `MediaAsset` on disk.

The rendered file is moved into the media directory under a generated
name, and the resulting asset records the backend and prompt that made
it — `MediaAsset.is_synthetic` then carries the platform disclosure through
to every publish.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import (
    MediaAsset,
    AssetSource,
    Account,
    Composition,
    CompositionClip,
    Event,
    EventLevel,
    GenerationJob,
    PipelineStatus,
)
from app.generation.base import (
    INPUT_MODE_SLIDESHOW,
    GenerationError,
    GenerationRequest,
    Progress,
    VideoBackend,
)
from app.generation.hints import enrich_generation_error
from app.generation.registry import get_backend
from app.services.generation_inputs import backend_supports_request, resolve_generation_inputs
from app.video.mux_audio import MuxError, mux_audio
from app.scheduler.queue import claim_due, fail
from app.services.budget import day_start, next_day, refuses
from app.services.media import probe_video

MAX_ATTEMPTS = 3

BUDGET_EVENT_KIND = "budget_reached"


def claim_due_generation_job(
    session: Session, *, now: datetime | None = None
) -> GenerationJob | None:
    return claim_due(session, GenerationJob, now=now)


def _fail_generation(
    session: Session,
    job: GenerationJob,
    message: str,
    *,
    retryable: bool,
    now: datetime | None,
) -> None:
    fail(
        session,
        job,
        enrich_generation_error(message, backend=job.backend),
        kind="generation_failed",
        retryable=retryable,
        max_attempts=MAX_ATTEMPTS,
        account_id=job.account_id,
        now=now,
    )


def run_generation_job(
    session: Session,
    job: GenerationJob,
    *,
    backend: VideoBackend | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> None:
    """Render one queued prompt and attach the resulting asset."""
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    if job.last_error:
        job.last_error = None
        session.add(job)
        session.commit()
    try:
        request = resolve_generation_inputs(session, job, settings)
    except GenerationError as exc:
        job.stage = ""
        job.queue_position = None
        _fail_generation(session, job, str(exc), retryable=False, now=now)
        return

    backend_name = (job.backend or "auto").strip().lower()
    if request.mode == INPUT_MODE_SLIDESHOW:
        backend_name = "slideshow"
        backend = get_backend(backend_name, settings)
    elif backend is None:
        backend = get_backend(backend_name, settings)
    if not backend_supports_request(backend, request):
        job.stage = ""
        job.queue_position = None
        _fail_generation(
            session,
            job,
            f"бэкенд {backend.name!r} не поддерживает режим {request.mode!r}",
            retryable=False,
            now=now,
        )
        return

    # Checked before the attempt is counted and before the request goes
    # out, because a ceiling that could only be read afterwards would not
    # be a ceiling. This is the one place all spending passes through: a
    # planned render, a hand-queued one, and a retry all arrive here.
    if _over_budget(session, job, request, backend, settings, now):
        return

    job.attempts += 1


    def note(progress: Progress) -> None:
        """Record where the render has got to, if it has moved.

        Committing only on a change keeps a five-second poll from writing
        the same row over and over for a render that sits in a queue.
        """
        if (job.stage, job.queue_position) == (
            progress.stage,
            progress.queue_position,
        ):
            return
        job.stage = progress.stage
        job.queue_position = progress.queue_position
        session.add(job)
        session.commit()

    try:
        result = backend.generate(request, settings.media_dir, on_progress=note)
    except GenerationError as exc:
        # A render that stopped is not at a stage any more, whichever way
        # it stopped — that part is this queue's own, not the policy's.
        job.stage = ""
        job.queue_position = None
        _fail_generation(session, job, str(exc), retryable=exc.retryable, now=now)
        return

    # Rename into the same uuid-style namespace uploads live in, so nothing
    # downstream has to care how a file arrived.
    final_name = f"{uuid.uuid4().hex}{result.video_path.suffix}"
    final_path = settings.media_dir / final_name
    result.video_path.rename(final_path)

    mux_note = ""
    audio_mode = (job.audio_mode or "none").strip().lower()
    if audio_mode not in {"", "none"}:
        try:
            mux_audio(
                final_path,
                mode=audio_mode,
                filename=job.audio_filename,
                settings=settings,
            )
        except MuxError as exc:
            mux_note = f"звук не приклеен: {exc}"[:240]

    probe = probe_video(final_path)
    asset = MediaAsset(
        filename=final_name,
        source=AssetSource.generated,
        generator=result.generator,
        prompt=job.prompt,
        duration_s=probe.duration_s or job.duration_s,
        width=probe.width or job.width,
        height=probe.height or job.height,
    )
    session.add(asset)
    session.flush()

    job.status = PipelineStatus.done
    job.stage = ""
    job.queue_position = None
    if result.backend:
        job.backend = result.backend
    job.asset_id = asset.id
    job.cost_usd = result.cost_usd
    job.seed = result.seed if result.seed is not None else job.seed
    job.last_error = mux_note or None
    job.finished_at = now

    session.add(job)
    session.add(
        Event(
            level=EventLevel.info,
            kind="generated",
            account_id=job.account_id,
            message=f"{result.generator} · ${result.cost_usd:.2f} · {job.prompt[:80]}",
        )
    )
    session.commit()

    if job.post_group is not None:
        # A post of several shots publishes the join, never the parts.
        _join_when_the_post_is_whole(session, job)
    elif job.auto_schedule and job.account_id is not None:
        _schedule_planned_post(session, job, asset)


def _over_budget(
    session: Session,
    job: GenerationJob,
    request: GenerationRequest,
    backend: VideoBackend,
    settings: Settings,
    now: datetime,
) -> bool:
    """Put the render back until tomorrow if it would break a ceiling.

    Deferred, not killed: the operator asked for this post, and a day's
    budget running out is not a reason to throw the work away. It waits
    for the ceiling to lift at the next UTC midnight.

    The attempt is deliberately not counted. A render that never ran has
    not failed, and counting it would use up the retries that exist for
    things going wrong.
    """
    cost = backend.estimate_cost(request)
    channel = session.get(Account, job.account_id) if job.account_id else None
    reason = refuses(session, cost, channel=channel, settings=settings, now=now)
    if reason is None:
        return False

    job.status = PipelineStatus.queued
    job.scheduled_at = next_day(now)
    job.stage = ""
    job.last_error = f"отложено до завтра — {reason}"
    session.add(job)

    # One line a day, not one per deferred render: a plan of twenty shots
    # would otherwise bury the day's log in the same sentence.
    already = session.execute(
        select(Event.id).where(
            Event.kind == BUDGET_EVENT_KIND,
            Event.account_id == job.account_id,
            Event.created_at >= day_start(now),
        )
    ).first()
    if already is None:
        session.add(
            Event(
                level=EventLevel.warn,
                kind=BUDGET_EVENT_KIND,
                account_id=job.account_id,
                message=f"рендер на паузе — {reason}",
                created_at=now,
            )
        )
    session.commit()
    return True


def _join_when_the_post_is_whole(session: Session, job: GenerationJob) -> None:
    """Queue the join once every shot of this post has rendered.

    Called after each shot lands, and does nothing until the last one
    does. Whichever shot finishes last is the one that queues the join —
    there is no separate pass watching for completeness, and so no way
    for a finished post to sit unnoticed because that pass never ran.
    """
    shots = (
        session.execute(
            select(GenerationJob)
            .where(GenerationJob.post_group == job.post_group)
            .order_by(GenerationJob.shot_index)
        )
        .scalars()
        .all()
    )

    blocked = {
        PipelineStatus.failed,
        PipelineStatus.dead,
        PipelineStatus.cancelled,
    }
    broken = [shot for shot in shots if shot.status in blocked]
    if broken:
        marker = f"post_group={job.post_group}"
        already = session.execute(
            select(Event.id).where(
                Event.kind == "post_join_blocked",
                Event.message.contains(marker),
            )
        ).first()
        if already is None:
            shot = broken[0]
            session.add(
                Event(
                    level=EventLevel.warn,
                    kind="post_join_blocked",
                    account_id=job.account_id,
                    message=(
                        f"{marker} склейка остановлена: кадр {shot.shot_index} — {shot.status.value}"
                    ),
                )
            )
            session.commit()
        return

    if any(
        shot.status is not PipelineStatus.done or shot.asset_id is None for shot in shots
    ):
        return

    already = session.execute(
        select(Composition).where(Composition.post_group == job.post_group)
    ).scalar_one_or_none()
    if already is not None:
        # Two shots finishing in the same tick must not queue two joins.
        return

    session.add(
        Composition(
            clips=[
                CompositionClip(asset_id=shot.asset_id, position=n)
                for n, shot in enumerate(shots)
            ],
            audio_asset_id=job.post_audio_asset_id,
            account_id=job.account_id,
            post_title=job.post_title,
            post_description=job.post_description,
            post_tags=job.post_tags,
            auto_schedule=job.auto_schedule,
            post_group=job.post_group,
        )
    )
    session.add(
        Event(
            level=EventLevel.info,
            kind="post_ready_to_join",
            account_id=job.account_id,
            message=(
                f"кадров отрендерено: {len(shots)} — "
                f"склеиваем {job.post_title[:60]}"
            ),
        )
    )
    session.commit()


def _schedule_planned_post(session: Session, job: GenerationJob, asset: MediaAsset) -> None:
    """Queue the publish the agent planned, at the channel's next slot.

    A scheduling failure must not undo a render that has already been paid
    for, so the asset stays and the problem is logged for the operator.
    """
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
            days_ahead=days_ahead_for_plan(session, plan_job_id=job.plan_job_id),
        )
    except PlanningError as exc:
        session.add(
            Event(
                level=EventLevel.warn,
                kind="schedule_failed",
                account_id=job.account_id,
                message=f"отрендерено, но не запланировано: {exc}",
            )
        )
        session.commit()
