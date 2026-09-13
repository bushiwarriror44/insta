"""Run the content agent for a channel and queue what it planned."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.planner import (
    MAX_IDEAS,
    AgentBackend,
    AgentError,
    ContentIdea,
    PlanRequest,
    TrackChoice,
)
from app.agent.registry import get_agent
from app.agent.sources import SourceError, SourceText, read_source
from app.config import Settings, get_settings
from app.db.models import (
    MediaAsset,
    AssetKind,
    Account,
    ChannelSource,
    AccountStatus,
    Event,
    EventLevel,
    GenerationJob,
    PipelineStatus,
    PlanJob,
    PostJob,
    RunTrigger,
)
from app.scheduler.queue import claim_due, fail
from app.services.agent_log import run_agent
from app.services.budget import refuses
from app.services.clarifications import settled_for

RECENT_LIMIT = 25
MAX_ATTEMPTS = 4


def recent_titles(session: Session, channel: Account) -> list[str]:
    """What this channel has already published or has queued.

    Given to the agent so it varies its output rather than rewriting
    yesterday's post.
    """
    published = (
        session.execute(
            select(PostJob.title)
            .where(PostJob.account_id == channel.id, PostJob.title != "")
            .order_by(PostJob.created_at.desc())
            .limit(RECENT_LIMIT)
        )
        .scalars()
        .all()
    )

    planned = (
        session.execute(
            select(GenerationJob.post_title)
            .where(
                GenerationJob.account_id == channel.id,
                GenerationJob.post_title != "",
                GenerationJob.status.in_([PipelineStatus.queued, PipelineStatus.running]),
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(RECENT_LIMIT)
        )
        .scalars()
        .all()
    )

    seen: list[str] = []
    for title in [*planned, *published]:
        if title not in seen:
            seen.append(title)
    return seen[:RECENT_LIMIT]


def gather_sources(
    session: Session, channel: Account, *, settings: Settings | None = None
) -> list[SourceText]:
    """Read what the channel points at, skipping whatever will not read.

    One broken source must not stop a plan: the failure is recorded on the
    source so the panel can show it, and planning carries on with the rest.
    """
    settings = settings or get_settings()
    rows = (
        session.execute(
            select(ChannelSource)
            .where(
                ChannelSource.account_id == channel.id, ChannelSource.enabled.is_(True)
            )
            .order_by(ChannelSource.id)
        )
        .scalars()
        .all()
    )

    gathered: list[SourceText] = []
    for row in rows:
        try:
            gathered.append(read_source(row.kind, row.value, row.label, settings))
            row.last_status = "ok"
        except SourceError as exc:
            row.last_status = str(exc)[:200]
        row.last_read_at = datetime.now(timezone.utc)
        session.add(row)

    session.commit()
    return gathered


def one_shot_costs(duration_s: float, settings: Settings) -> float:
    """What the cheapest thing a plan can queue would cost.

    An unconfigured or unknown backend quotes nothing, which means this
    check never refuses on a guess — the render itself still cannot go
    over the ceiling.
    """
    from app.generation.base import GenerationRequest
    from app.generation.registry import get_backend

    try:
        backend = get_backend(settings.video_backend, settings)
    except NotImplementedError:
        return 0.0
    return backend.estimate_cost(GenerationRequest(prompt="", duration_s=duration_s))


def library_tracks(session: Session) -> list[MediaAsset]:
    """The soundtracks the agent may choose from.

    Only named ones: a uuid filename is nothing a model — or a person —
    can recognise, so an unnamed track is not offered rather than offered
    unidentifiably.
    """
    return list(
        session.execute(
            select(MediaAsset)
            .where(
                MediaAsset.kind == AssetKind.audio,
                MediaAsset.label != "",
                MediaAsset.file_removed_at.is_(None),
            )
            .order_by(MediaAsset.created_at.desc())
        )
        .scalars()
        .all()
    )


def match_track(name: str | None, tracks: list[MediaAsset]) -> MediaAsset | None:
    """The track the agent asked for, if it is one that was offered.

    A name that was not on the list is a name the model made up. The post
    goes out silent rather than with something nobody chose.
    """
    if not name:
        return None
    wanted = name.strip().casefold()
    for track in tracks:
        if track.label.casefold() == wanted:
            return track
    return None


def queue_ideas(
    session: Session,
    channel: Account,
    ideas: list[ContentIdea],
    *,
    duration_s: float = 5.0,
    auto_schedule: bool = True,
    tracks: list[MediaAsset] | None = None,
    plan_job_id: int | None = None,
) -> list[GenerationJob]:
    """Turn planned posts into the renders that make them.

    One render per shot. A post of several shots is tied together by a
    group: the publish belongs to the joined result, not to any one shot,
    so the individual renders never schedule themselves.
    """
    tracks = tracks if tracks is not None else library_tracks(session)
    jobs: list[GenerationJob] = []
    invented: list[str] = []
    engine = get_settings().video_backend or "auto"

    for idea in ideas:
        track = match_track(idea.soundtrack, tracks)
        if idea.soundtrack and track is None:
            invented.append(idea.soundtrack)

        # A one-shot post with no soundtrack is a clip that publishes as
        # it is, exactly as before: no group, no join, no encode pass.
        # A track means it has to be composed even at one shot.
        needs_join = len(idea.shots) > 1 or track is not None
        group = uuid.uuid4().hex[:32] if needs_join else None

        for index, shot in enumerate(idea.shots):
            jobs.append(
                GenerationJob(
                    prompt=shot,
                    backend=engine,
                    duration_s=duration_s,
                    account_id=channel.id,
                    post_title=idea.title,
                    post_description=idea.description,
                    post_tags=", ".join(idea.tags),
                    auto_schedule=auto_schedule,
                    post_group=group,
                    shot_index=index,
                    post_audio_asset_id=track.id if track else None,
                    plan_job_id=plan_job_id,
                )
            )

    session.add_all(jobs)
    shots = len(jobs)
    posts = len(ideas)
    session.add(
        Event(
            level=EventLevel.info,
            kind="planned",
            account_id=channel.id,
            message=(
                f"agent planned {posts} posts for {channel.username}"
                + (f" — {shots} shots" if shots != posts else "")
            ),
        )
    )
    if invented:
        session.add(
            Event(
                level=EventLevel.warn,
                kind="unknown_soundtrack",
                account_id=channel.id,
                message=(
                    "the agent asked for tracks that are not in the library, "
                    f"so those posts are silent: {', '.join(sorted(set(invented)))}"
                ),
            )
        )

    session.commit()
    for job in jobs:
        session.refresh(job)
    return jobs


def plan_for_channel(
    session: Session,
    channel: Account,
    count: int,
    *,
    duration_s: float = 5.0,
    auto_schedule: bool = True,
    agent: AgentBackend | None = None,
    settings: Settings | None = None,
    plan_job_id: int | None = None,
    spread_over_days: int | None = None,
    avoid: list[str] | None = None,
) -> list[GenerationJob]:
    """Ask the agent for `count` posts and queue the renders."""
    settings = settings or get_settings()
    agent = agent or get_agent(settings=settings)

    if channel.status is AccountStatus.blocked:
        raise AgentError("каналу нужна повторная авторизация, иначе публиковать нельзя")

    # Asked as "can today still afford one shot", not "would spending
    # nothing be too much" — a day sitting exactly on its ceiling passes
    # the second question and can still pay for nothing. The render check
    # is the real ceiling; this only avoids paying for a plan that would
    # fill a queue unable to move until tomorrow.
    exhausted = refuses(
        session,
        one_shot_costs(duration_s, settings),
        channel=channel,
        settings=settings,
    )
    if exhausted:
        raise AgentError(f"not planning today — {exhausted}")

    sources = gather_sources(session, channel, settings=settings)
    tracks = library_tracks(session)
    result = run_agent(
        session,
        agent,
        PlanRequest(
            brief=channel.brief or "",
            count=count,
            platform=(
                channel.platform.value
                if hasattr(channel.platform, "value")
                else (channel.platform or "instagram")
            ),
            recent_titles=recent_titles(session, channel),
            duration_s=duration_s,
            sources=sources,
            settled=settled_for(session, channel.id),
            tracks=[
                TrackChoice(label=track.label, duration_s=track.duration_s)
                for track in tracks
            ],
            spread_over_days=spread_over_days,
            avoid=avoid,
        ),
        account_id=channel.id,
        trigger=RunTrigger.job,
        plan_job_id=plan_job_id,
        sources=sources,
    )
    return queue_ideas(
        session,
        channel,
        result.ideas,
        duration_s=duration_s,
        auto_schedule=auto_schedule,
        tracks=tracks,
        plan_job_id=plan_job_id,
    )


def claim_due_plan_job(
    session: Session, *, now: datetime | None = None
) -> PlanJob | None:
    """Pick the oldest planning request that is due."""
    return claim_due(session, PlanJob, now=now)


def run_plan_job(
    session: Session,
    job: PlanJob,
    *,
    agent: AgentBackend | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> None:
    """Run one planning request, retrying what is worth retrying.

    A rate limit or an unreachable model is worth another attempt later; a
    brief the model declines is not, and dying loudly is what gets the
    operator told through the alert outbox.
    """
    now = now or datetime.now(timezone.utc)
    job.attempts += 1

    try:
        account = session.get(Account, job.account_id)
        if account is None:
            raise AgentError("аккаунт не найден")
        queued = plan_for_channel(
            session,
            account,
            job.count,
            duration_s=job.duration_s,
            auto_schedule=job.auto_schedule,
            agent=agent,
            settings=settings,
            plan_job_id=job.id,
            spread_over_days=job.spread_over_days,
        )
    except AgentError as exc:
        fail(
            session,
            job,
            str(exc),
            kind="planning_failed",
            retryable=exc.retryable,
            max_attempts=MAX_ATTEMPTS,
            account_id=job.account_id,
            now=now,
        )
        return

    job.status = PipelineStatus.done
    job.planned = len(queued)
    job.last_error = None
    job.finished_at = now
    session.add(job)
    session.commit()


def posts_in_a_week(channel: Account) -> int:
    """How many posts a week of this channel's rhythm holds.

    Read off the channel rather than asked for, because the operator has
    already decided the rhythm and being asked it twice is how the two
    answers end up disagreeing.
    """
    return max(1, min(int(channel.daily_post_cap or 1) * 7, MAX_IDEAS))


def replan_post(
    session: Session,
    channel: Account,
    jobs: list[GenerationJob],
    *,
    agent: AgentBackend | None = None,
    settings: Settings | None = None,
) -> list[GenerationJob]:
    """Ask again for one post, replacing the renders that were queued for it.

    Only ever called on renders that have not run, so nothing paid for is
    thrown away. The other posts still queued for this channel are handed
    over as things not to repeat — otherwise the replacement is as likely
    to land on the subject the operator was trying to move away from.
    """
    settings = settings or get_settings()
    if any(job.status is not PipelineStatus.queued for job in jobs):
        raise AgentError("this post has already started rendering")

    doomed = {job.id for job in jobs}
    still_planned = list(
        session.execute(
            select(GenerationJob.post_title).where(
                GenerationJob.account_id == channel.id,
                GenerationJob.status.in_([PipelineStatus.queued, PipelineStatus.running]),
                GenerationJob.post_title != "",
                GenerationJob.id.not_in(doomed),
            )
        ).scalars()
    )

    replacement = plan_for_channel(
        session,
        channel,
        1,
        duration_s=jobs[0].duration_s,
        auto_schedule=jobs[0].auto_schedule,
        agent=agent,
        settings=settings,
        avoid=sorted(set(still_planned)),
    )

    # Removed only once the replacement exists: a failed call must not
    # leave the channel with one post fewer than it had.
    for job in jobs:
        session.delete(job)
    session.add(
        Event(
            level=EventLevel.info,
            kind="replanned",
            account_id=channel.id,
            message=(
                f"asked again for {jobs[0].post_title[:60]!r} — "
                f"{replacement[0].post_title[:60]!r} instead"
            ),
        )
    )
    session.commit()
    return replacement


def shots_of_post(session: Session, job: GenerationJob) -> list[GenerationJob]:
    """Every render belonging to the same planned post as this one."""
    if job.post_group is None:
        return [job]
    return list(
        session.execute(
            select(GenerationJob)
            .where(GenerationJob.post_group == job.post_group)
            .order_by(GenerationJob.shot_index)
        )
        .scalars()
        .all()
    )
