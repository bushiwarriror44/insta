"""Start and stop the agent/worker from the panel."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.api.schemas import WorkerProcessOut
from app.scheduler.heartbeat import worker_status
from app.services import worker_control

router = APIRouter(prefix="/api/worker", tags=["worker"], dependencies=[AuthDep])


def _payload(db: Session) -> WorkerProcessOut:
    beat = worker_status(db)
    ours = worker_control.status()
    running = ours.alive or (beat.known and not beat.stale)
    return WorkerProcessOut(
        running=running,
        ours=ours.alive,
        pid=ours.pid,
        seen_at=beat.seen_at,
        note=beat.note or "",
    )


@router.get("", response_model=WorkerProcessOut)
def read_worker(db: Session = Depends(get_db)) -> WorkerProcessOut:
    return _payload(db)


@router.post("/start", response_model=WorkerProcessOut)
def start_worker(db: Session = Depends(get_db)) -> WorkerProcessOut:
    beat = worker_status(db)
    ours = worker_control.status()
    if beat.known and not beat.stale and not ours.alive:
        raise HTTPException(
            status_code=409,
            detail=(
                "Агент уже работает (терминал или Docker). "
                "Панель может остановить только процесс, который запустила сама."
            ),
        )
    try:
        worker_control.start()
    except worker_control.WorkerProblem as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _payload(db)


@router.post("/stop", response_model=WorkerProcessOut)
def stop_worker(db: Session = Depends(get_db)) -> WorkerProcessOut:
    ours = worker_control.status()
    if not ours.alive:
        raise HTTPException(
            status_code=409,
            detail="Панель может остановить только агента, которого запустила сама.",
        )
    worker_control.stop()
    return _payload(db)
