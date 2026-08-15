"""Public health probe (no auth)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import HealthOut
from app.panel.settings_store import auth_is_required, get_or_create_panel_settings

router = APIRouter(prefix="/api/health", tags=["health"])


__VERSION__ = "0.2.0"


@router.get("", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    get_or_create_panel_settings(db)
    return HealthOut(
        ok=True,
        version=__VERSION__,
        auth_required=auth_is_required(db),
    )
