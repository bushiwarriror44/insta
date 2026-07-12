"""Diagnostic run log endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import DiagnosticLogLineOut, DiagnosticRunOut
from app.db import Account, DiagnosticRun, DiagnosticRunKind
from app.diagnostics.collector import load_run_lines

router = APIRouter(prefix="/api/diagnostic-runs", tags=["diagnostics"], dependencies=[AuthDep])


def _to_run_out(run: DiagnosticRun, *, account_username: str | None = None) -> DiagnosticRunOut:
    logs = load_run_lines(run)
    kind = run.kind.value if hasattr(run.kind, "value") else str(run.kind)
    status = run.status.value if hasattr(run.status, "value") else str(run.status)
    return DiagnosticRunOut(
        id=run.id,
        kind=kind,  # type: ignore[arg-type]
        account_id=run.account_id,
        account_username=account_username,
        job_id=run.job_id,
        status=status,  # type: ignore[arg-type]
        summary=run.summary,
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in logs],
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


@router.get("", response_model=List[DiagnosticRunOut])
def list_diagnostic_runs(
    username: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    job_id: Optional[int] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> List[DiagnosticRunOut]:
    stmt = select(DiagnosticRun).order_by(DiagnosticRun.created_at.desc()).limit(limit)
    if username:
        account = db.scalar(select(Account).where(Account.username == username))
        if account is None:
            return []
        stmt = stmt.where(DiagnosticRun.account_id == account.id)
    if kind:
        try:
            kind_enum = DiagnosticRunKind(kind)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid kind: {kind}") from exc
        stmt = stmt.where(DiagnosticRun.kind == kind_enum)
    if job_id is not None:
        stmt = stmt.where(DiagnosticRun.job_id == job_id)

    runs = db.scalars(stmt).all()
    usernames: dict[int, str] = {}
    if runs:
        ids = {r.account_id for r in runs}
        rows = db.execute(select(Account.id, Account.username).where(Account.id.in_(ids))).all()
        usernames = {int(aid): uname for aid, uname in rows}

    return [_to_run_out(r, account_username=usernames.get(r.account_id)) for r in runs]


@router.get("/{run_id}", response_model=DiagnosticRunOut)
def get_diagnostic_run(run_id: int, db: Session = Depends(get_db)) -> DiagnosticRunOut:
    run = db.get(DiagnosticRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Diagnostic run not found")
    account = db.get(Account, run.account_id)
    return _to_run_out(run, account_username=account.username if account else None)
