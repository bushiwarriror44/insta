"""Owner-only panel operator (sub-admin) management."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OwnerDep, get_db
from app.api.schemas import PanelOperatorCreateIn, PanelOperatorCreatedOut, PanelOperatorOut
from app.auth.passwords import generate_operator_password, hash_password
from app.db import PanelOperator

router = APIRouter(prefix="/api/operators", tags=["operators"], dependencies=[OwnerDep])


def _serialize(row: PanelOperator, *, password: str | None = None) -> PanelOperatorOut | PanelOperatorCreatedOut:
    base = {
        "id": row.id,
        "label": row.label,
        "created_at": row.created_at,
        "revoked_at": row.revoked_at,
        "last_used_at": row.last_used_at,
        "active": row.revoked_at is None,
    }
    if password is not None:
        return PanelOperatorCreatedOut(**base, password=password)
    return PanelOperatorOut(**base)


@router.get("", response_model=list[PanelOperatorOut])
def list_operators(db: Session = Depends(get_db)) -> list[PanelOperatorOut]:
    rows = db.scalars(select(PanelOperator).order_by(PanelOperator.created_at.desc())).all()
    return [_serialize(r) for r in rows]  # type: ignore[misc]


@router.post("", response_model=PanelOperatorCreatedOut, status_code=status.HTTP_201_CREATED)
def create_operator(
    payload: PanelOperatorCreateIn,
    db: Session = Depends(get_db),
) -> PanelOperatorCreatedOut:
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Метка не может быть пустой")

    existing = db.scalar(select(PanelOperator).where(PanelOperator.label == label))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Оператор с меткой '{label}' уже существует",
        )

    password = generate_operator_password()
    row = PanelOperator(label=label, password_hash=hash_password(password))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row, password=password)  # type: ignore[return-value]


@router.post("/{operator_id}/revoke", response_model=PanelOperatorOut)
def revoke_operator(operator_id: int, db: Session = Depends(get_db)) -> PanelOperatorOut:
    row = db.get(PanelOperator, operator_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Оператор не найден")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    return _serialize(row)  # type: ignore[return-value]
