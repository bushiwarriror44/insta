"""Questions the agent asked about a brief, and the operator's answers.

The agent never blocks on one of these. It plans the batch, says which
way it guessed, and asks — so a question is a place the plan may have
gone wrong, not a thing to wait on. An answered question is handed to
every later plan for that channel, which is the whole value: the operator
says it once instead of rewriting the brief each time the same gap bites.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.planner import AgentQuestion
from app.db.models import Clarification, question_key

#: A fresh set is filed only when the last one has been dealt with, and
#: never more than this many at a time.
MAX_OPEN = 3


def settled_for(session: Session, account_id: int) -> list[tuple[str, str]]:
    """Answered questions, oldest first, to hand to the next plan."""
    rows = (
        session.execute(
            select(Clarification)
            .where(
                Clarification.account_id == account_id,
                Clarification.answer.is_not(None),
            )
            .order_by(Clarification.answered_at)
        )
        .scalars()
        .all()
    )
    return [(row.question, row.answer or "") for row in rows]


def open_questions(session: Session, account_id: int) -> list[Clarification]:
    return list(
        session.execute(
            select(Clarification)
            .where(
                Clarification.account_id == account_id,
                Clarification.answer.is_(None),
                Clarification.dismissed.is_(False),
            )
            .order_by(Clarification.asked_at.desc())
        )
        .scalars()
        .all()
    )


def record_questions(
    session: Session,
    account_id: int,
    questions: list[AgentQuestion],
    *,
    agent_run_id: int | None = None,
    now: datetime | None = None,
) -> list[Clarification]:
    """File what the agent asked, ignoring what it has asked before.

    A question already answered is not raised again: the answer went into
    the prompt, and the model asking anyway is a model that did not read
    it, not a new gap in the brief.

    Nothing is filed while the channel still has an open question. Every
    run reports what it decided, and the wording drifts each time — "who
    is this for" one run, "what audience is this aimed at" the next — so
    filing them all buries the operator in the same question rephrased.
    The backlog refreshes once it has been dealt with; the per-run detail
    is on the run either way.
    """
    now = now or datetime.now(timezone.utc)
    if open_questions(session, account_id):
        return []

    known = {
        row.question_key
        for row in session.execute(
            select(Clarification).where(Clarification.account_id == account_id)
        ).scalars()
    }

    filed: list[Clarification] = []
    for question in questions[:MAX_OPEN]:
        key = question_key(question.question)
        if not key or key in known:
            continue
        known.add(key)
        row = Clarification(
            account_id=account_id,
            agent_run_id=agent_run_id,
            question=question.question,
            question_key=key,
            why=question.why,
            assumed=question.assumed,
            asked_at=now,
        )
        session.add(row)
        filed.append(row)

    if filed:
        session.commit()
        for row in filed:
            session.refresh(row)
    return filed


def answer(
    session: Session,
    clarification: Clarification,
    text: str,
    *,
    by: str = "",
    now: datetime | None = None,
) -> Clarification:
    """Answer a question. From here it is part of the brief."""
    clarification.answer = text.strip()
    clarification.answered_by = by
    clarification.answered_at = now or datetime.now(timezone.utc)
    clarification.dismissed = False
    session.add(clarification)
    session.commit()
    session.refresh(clarification)
    return clarification


def dismiss(session: Session, clarification: Clarification) -> Clarification:
    """Set a question aside without answering it.

    Kept rather than deleted: what the agent assumed is on record, and
    the question does not come back the next time it is asked.
    """
    clarification.dismissed = True
    session.add(clarification)
    session.commit()
    session.refresh(clarification)
    return clarification
