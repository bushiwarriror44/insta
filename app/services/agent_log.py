"""The record of what the agent was asked and what it answered.

Every model call goes through `run_agent`, so there is no path that plans
without leaving a row. That matters more than it sounds: the reason to
keep a log is the run that went wrong, and a recorder the caller has to
remember to invoke is exactly the one that is missing on the day it is
needed.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.planner import (
    AgentBackend,
    AgentError,
    PlanRequest,
    PlanResult,
    build_prompt,
)
from app.agent.sources import SourceText
from app.db.models import AgentRun, RunTrigger
from app.services.clarifications import record_questions

#: Prompts carry reference material and answers carry every idea, so both
#: can be long. Enough to read the whole thing in the ordinary case, and a
#: ceiling so one run cannot fill the database.
MAX_TEXT = 20_000

#: Runs kept per channel. Old ones answer nothing that the newer ones do
#: not, and the prompts are the bulky part of this table.
KEEP_PER_CHANNEL = 200


def clip(text: str, limit: int = MAX_TEXT) -> str:
    """Trim for storage, saying so rather than truncating silently."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… trimmed, {len(text) - limit} more characters"


def run_agent(
    session: Session,
    agent: AgentBackend,
    request: PlanRequest,
    *,
    account_id: int,
    trigger: RunTrigger = RunTrigger.job,
    plan_job_id: int | None = None,
    sources: list[SourceText] | None = None,
) -> PlanResult:
    """Plan, record the attempt, and let a failure through unchanged.

    A failed call is written before the error is re-raised: the caller's
    retry and backoff are unaffected, and the operator gets to see the
    attempt that did not work.
    """
    started = time.monotonic()
    run = AgentRun(
        account_id=account_id,
        plan_job_id=plan_job_id,
        trigger=trigger,
        backend=agent.name,
        requested=request.count,
        sources_json=json.dumps([source.label for source in sources or []]),
    )

    try:
        result = agent.plan(request)
    except AgentError as exc:
        run.ok = False
        run.error = str(exc)[:2000]
        # The backend may have failed before building a prompt; rebuild
        # it from the request so the log still shows what was asked.
        run.prompt = clip(build_prompt(request))
        run.duration_ms = _elapsed(started)
        _record(session, run)
        raise

    run.prompt = clip(result.prompt or "")
    run.raw = clip(result.raw or "")
    run.model = result.usage.model
    run.returned = len(result.ideas)
    run.ideas_json = json.dumps([idea.model_dump() for idea in result.ideas])
    run.input_tokens = result.usage.input_tokens
    run.output_tokens = result.usage.output_tokens
    run.cost_usd = result.usage.cost_usd
    run.retried = result.usage.retried
    run.questions_json = json.dumps(
        [question.model_dump() for question in result.questions]
    )
    run.duration_ms = _elapsed(started)
    _record(session, run)

    # Filed after the run exists, so a question carries the id of the run
    # that raised it and the prompt that produced it can be read back.
    record_questions(session, account_id, result.questions, agent_run_id=run.id)
    return result


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _record(session: Session, run: AgentRun) -> None:
    session.add(run)
    session.commit()
    session.refresh(run)
    prune(session, run.account_id)


def prune(session: Session, account_id: int, keep: int = KEEP_PER_CHANNEL) -> int:
    """Drop this channel's oldest runs past `keep`, returning how many went."""
    stale = (
        session.execute(
            select(AgentRun.id)
            .where(AgentRun.account_id == account_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .offset(keep)
        )
        .scalars()
        .all()
    )

    if not stale:
        return 0

    for run in session.execute(
        select(AgentRun).where(AgentRun.id.in_(stale))
    ).scalars():
        session.delete(run)
    session.commit()
    return len(stale)


def recent_runs(
    session: Session,
    *,
    account_id: int | None = None,
    limit: int = 50,
    failures_only: bool = False,
) -> list[AgentRun]:
    query = select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    if account_id is not None:
        query = query.where(AgentRun.account_id == account_id)
    if failures_only:
        query = query.where(AgentRun.ok.is_(False))
    return list(session.execute(query.limit(limit)).scalars().all())


def spend_since(session: Session, since: datetime) -> tuple[int, float]:
    """How many runs since `since`, and what they cost."""
    runs = (
        session.execute(select(AgentRun.cost_usd).where(AgentRun.created_at >= since))
        .scalars()
        .all()
    )
    return len(runs), round(sum(runs), 4)


def day_spend(session: Session, now: datetime | None = None) -> tuple[int, float]:
    now = now or datetime.now(timezone.utc)
    return spend_since(session, now.replace(hour=0, minute=0, second=0, microsecond=0))
