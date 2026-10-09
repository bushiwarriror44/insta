"""Content-agent planning: PlanJob, queue_ideas, sources, budget gates."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agent.planner import AgentError, ContentIdea, PlanResult, Usage, build_prompt
from app.db.models import (
    AccountStatus,
    ChannelSource,
    Event,
    GenerationJob,
    PipelineStatus,
    PlanJob,
    SourceKind,
)
from app.services.planning import (
    MAX_ATTEMPTS,
    gather_sources,
    plan_for_channel,
    queue_ideas,
    replan_post,
    run_plan_job,
)
from app.services.scheduling import days_ahead_for_plan
from tests.unit.test_factory_merge import StubAgent


class FailingAgent:
    name = "fail"

    def __init__(self, *, retryable: bool = False) -> None:
        self.retryable = retryable

    def healthcheck(self):
        return True

    def plan(self, request):
        raise AgentError("model unavailable", retryable=self.retryable)


class TwoShotAgent(StubAgent):
    def plan(self, request):
        return PlanResult(
            ideas=[
                ContentIdea(
                    shots=[
                        "misty ridge wide, slow push",
                        "pine needles close-up, dew",
                    ],
                    title="Ridge at dawn",
                    description="Fog in pines.",
                    tags=["nature"],
                )
            ],
            questions=[],
            usage=Usage(model="stub", input_tokens=1, output_tokens=1),
            prompt=build_prompt(request),
            raw="{}",
        )


class ReplacementAgent(StubAgent):
    def plan(self, request):
        return PlanResult(
            ideas=[
                ContentIdea(
                    shots=["ocean cliff at sunset"],
                    title="Cliff replace",
                    description="Waves.",
                    tags=["sea"],
                )
            ],
            questions=[],
            usage=Usage(model="stub", input_tokens=1, output_tokens=1),
            prompt=build_prompt(request),
            raw="{}",
        )


def _plan_job(db_session, account, **kwargs) -> PlanJob:
    job = PlanJob(
        account_id=account.id,
        count=kwargs.get("count", 1),
        duration_s=kwargs.get("duration_s", 5.0),
        auto_schedule=kwargs.get("auto_schedule", False),
        spread_over_days=kwargs.get("spread_over_days"),
        status=PipelineStatus.queued,
        scheduled_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_run_plan_job_marks_done_and_links_generations(db_session, make_account):
    account = make_account()
    account.brief = "nature"
    db_session.commit()
    job = _plan_job(db_session, account, count=1)

    run_plan_job(db_session, job, agent=StubAgent())

    db_session.refresh(job)
    assert job.status is PipelineStatus.done
    assert job.planned == 1
    gen = db_session.scalar(
        select(GenerationJob).where(GenerationJob.plan_job_id == job.id)
    )
    assert gen is not None
    assert gen.account_id == account.id


def test_run_plan_job_retryable_failure_requeues(db_session, make_account):
    account = make_account()
    account.brief = "nature"
    db_session.commit()
    job = _plan_job(db_session, account)

    run_plan_job(db_session, job, agent=FailingAgent(retryable=True))

    db_session.refresh(job)
    assert job.attempts == 1
    assert job.status is PipelineStatus.queued
    assert "model unavailable" in (job.last_error or "")


def test_run_plan_job_non_retryable_goes_dead(db_session, make_account):
    account = make_account()
    account.brief = "nature"
    db_session.commit()
    job = _plan_job(db_session, account)

    run_plan_job(db_session, job, agent=FailingAgent(retryable=False))

    db_session.refresh(job)
    assert job.status is PipelineStatus.dead


def test_gather_sources_records_broken_source_without_aborting(db_session, make_account, monkeypatch):
    from app.config import settings

    account = make_account()
    monkeypatch.setattr(settings, "reference_allowed_hosts", "example.com", raising=False)
    row = ChannelSource(
        account_id=account.id,
        kind=SourceKind.url,
        value="https://evil.example/not-allowed-host.test",
        label="bad",
        enabled=True,
    )
    db_session.add(row)
    db_session.commit()

    gathered = gather_sources(db_session, account, settings=settings)

    assert gathered == []
    db_session.refresh(row)
    assert row.last_status
    assert "REFERENCE_ALLOWED_HOSTS" in row.last_status or "not in" in row.last_status


def test_queue_ideas_multi_shot_shares_post_group(db_session, make_account):
    account = make_account()
    ideas = [
        ContentIdea(
            shots=["shot one long enough here", "shot two long enough here"],
            title="Two shots",
            description="desc",
            tags=["a"],
        )
    ]
    jobs = queue_ideas(db_session, account, ideas, auto_schedule=False)
    assert len(jobs) == 2
    assert jobs[0].post_group == jobs[1].post_group
    assert jobs[0].shot_index == 0
    assert jobs[1].shot_index == 1


def test_queue_ideas_unknown_soundtrack_emits_event(db_session, make_account):
    account = make_account()
    ideas = [
        ContentIdea(
            shots=["a misty pine ridge at dawn, slow drone push"],
            title="Silent",
            description="desc",
            tags=["a"],
            soundtrack="Made Up Track",
        )
    ]
    queue_ideas(db_session, account, ideas, tracks=[], auto_schedule=False)
    kind = db_session.scalar(
        select(Event.kind).where(
            Event.account_id == account.id,
            Event.kind == "unknown_soundtrack",
        )
    )
    assert kind == "unknown_soundtrack"


def test_plan_for_channel_refuses_blocked_account(db_session, make_account):
    account = make_account()
    account.status = AccountStatus.blocked
    db_session.commit()
    with pytest.raises(AgentError, match="авторизац"):
        plan_for_channel(db_session, account, 1, agent=StubAgent())


def test_plan_for_channel_refuses_when_budget_exhausted(db_session, make_account, monkeypatch):
    account = make_account()
    account.brief = "x"
    db_session.commit()

    def _refuse(*_a, **_k):
        return "daily cap"

    monkeypatch.setattr("app.services.planning.refuses", _refuse)
    with pytest.raises(AgentError, match="not planning"):
        plan_for_channel(db_session, account, 1, agent=StubAgent())


def test_days_ahead_for_plan_reads_spread_from_plan_job(db_session, make_account):
    account = make_account()
    job = _plan_job(db_session, account, spread_over_days=7)
    assert days_ahead_for_plan(db_session, plan_job_id=job.id) == 7


def test_replan_post_replaces_queued_shots(db_session, make_account):
    account = make_account()
    account.brief = "nature"
    db_session.commit()
    first = plan_for_channel(
        db_session, account, 1, agent=TwoShotAgent(), auto_schedule=False
    )
    assert len(first) == 2
    old_ids = {j.id for j in first}

    replacement = replan_post(db_session, account, first, agent=ReplacementAgent())
    assert len(replacement) == 1
    assert replacement[0].post_title == "Cliff replace"
    for oid in old_ids:
        assert db_session.get(GenerationJob, oid) is None


def test_run_plan_job_exhausts_retries_then_dead(db_session, make_account):
    account = make_account()
    account.brief = "nature"
    db_session.commit()
    job = _plan_job(db_session, account)
    agent = FailingAgent(retryable=True)
    for _ in range(MAX_ATTEMPTS):
        db_session.refresh(job)
        if job.status is PipelineStatus.dead:
            break
        run_plan_job(db_session, job, agent=agent)
    db_session.refresh(job)
    assert job.status is PipelineStatus.dead
    assert job.attempts == MAX_ATTEMPTS
