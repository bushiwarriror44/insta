"""Clarifications: open questions gate filing; settled answers in prompt."""

from __future__ import annotations

from app.agent.planner import AgentQuestion, PlanRequest, build_prompt
from app.db.models import Clarification, question_key
from app.services.clarifications import answer, record_questions, settled_for


def test_record_questions_skips_while_an_open_question_exists(db_session, make_account):
    account = make_account()
    db_session.add(
        Clarification(
            account_id=account.id,
            question="Who is this for?",
            question_key=question_key("Who is this for?"),
        )
    )
    db_session.commit()

    filed = record_questions(
        db_session,
        account.id,
        [
            AgentQuestion(
                question="What tone?",
                why="brief silent",
                assumed="calm",
            )
        ],
    )
    assert filed == []
    count = db_session.query(Clarification).filter_by(account_id=account.id).count()
    assert count == 1


def test_record_questions_after_answer(db_session, make_account):
    account = make_account()
    open_row = Clarification(
        account_id=account.id,
        question="Who is this for?",
        question_key=question_key("Who is this for?"),
    )
    db_session.add(open_row)
    db_session.commit()
    answer(db_session, open_row, "travelers")

    filed = record_questions(
        db_session,
        account.id,
        [
            AgentQuestion(
                question="What tone?",
                why="brief silent",
                assumed="calm",
            )
        ],
    )
    assert len(filed) == 1
    assert filed[0].question == "What tone?"


def test_settled_for_appears_in_plan_prompt(db_session, make_account):
    account = make_account()
    row = Clarification(
        account_id=account.id,
        question="Who is this for?",
        question_key=question_key("Who is this for?"),
    )
    db_session.add(row)
    db_session.commit()
    answer(db_session, row, "outdoor lovers")

    settled = settled_for(db_session, account.id)
    prompt = build_prompt(PlanRequest(brief="nature", count=1, settled=settled))
    assert "outdoor lovers" in prompt
    assert "Who is this for?" in prompt
