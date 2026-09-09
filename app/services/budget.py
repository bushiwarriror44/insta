"""What the factory has spent today, and what it may still spend.

Every cost in this system was recorded and none of it was ever checked.
A render that fails in a way worth retrying costs money each time it is
tried; a plan of five posts is up to twenty renders now rather than five;
and both of those run overnight with nobody watching. The arithmetic to
notice was already there — what was missing was anything that stops.

The ceiling is a UTC day, which matters: a cap that reset at the
operator's local midnight would reset at a different moment for the
worker, and a job deferred to "tomorrow" would come back an hour early
and spend anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AgentRun, Account, GenerationJob


@dataclass(slots=True)
class Budget:
    """What one ceiling has left in it."""

    #: The ceiling itself. None where none is set.
    cap_usd: float | None
    spent_usd: float

    @property
    def remaining_usd(self) -> float | None:
        if self.cap_usd is None:
            return None
        return max(0.0, round(self.cap_usd - self.spent_usd, 4))

    def would_exceed(self, cost: float) -> bool:
        return self.cap_usd is not None and self.spent_usd + cost > self.cap_usd


def day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def next_day(now: datetime) -> datetime:
    """When the ceiling lifts. What a deferred render waits for."""
    return day_start(now) + timedelta(days=1)


def spent_today(
    session: Session,
    *,
    account_id: int | None = None,
    now: datetime | None = None,
) -> float:
    """Rendering and planning paid for since midnight UTC.

    Renders are counted from `finished_at`, because that is when the
    money left. A render still running has not been billed yet and is
    accounted for by the estimate the caller is checking.
    """
    now = now or datetime.now(timezone.utc)
    since = day_start(now)

    renders = select(func.coalesce(func.sum(GenerationJob.cost_usd), 0.0)).where(
        GenerationJob.finished_at >= since
    )
    runs = select(func.coalesce(func.sum(AgentRun.cost_usd), 0.0)).where(
        AgentRun.created_at >= since
    )
    if account_id is not None:
        renders = renders.where(GenerationJob.account_id == account_id)
        runs = runs.where(AgentRun.account_id == account_id)

    return round(
        session.execute(renders).scalar_one() + session.execute(runs).scalar_one(), 4
    )


def factory_budget(
    session: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> Budget:
    settings = settings or get_settings()
    cap = settings.daily_spend_cap_usd or None
    return Budget(cap_usd=cap, spent_usd=spent_today(session, now=now))


def channel_budget(
    session: Session, channel: Account, *, now: datetime | None = None
) -> Budget:
    cap = channel.daily_spend_cap_usd or None
    return Budget(
        cap_usd=cap, spent_usd=spent_today(session, account_id=channel.id, now=now)
    )


def refuses(
    session: Session,
    cost: float,
    *,
    channel: Account | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str | None:
    """Why this spend is not allowed today, or None if it is.

    Both ceilings apply. A channel with its own budget is still bounded
    by the factory's, or one channel could eat everything.
    """
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)

    if channel is not None:
        budget = channel_budget(session, channel, now=now)
        if budget.would_exceed(cost):
            return (
                f"{channel.username} has spent ${budget.spent_usd:.2f} of its "
                f"${budget.cap_usd:.2f} for today"
            )

    budget = factory_budget(session, settings=settings, now=now)
    if budget.would_exceed(cost):
        return (
            f"the factory has spent ${budget.spent_usd:.2f} of its "
            f"${budget.cap_usd:.2f} for today"
        )
    return None
