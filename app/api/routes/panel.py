"""Public panel gate (no auth)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import PanelGateOut
from app.panel.settings_store import (
    gate_is_enabled,
    get_or_create_panel_settings,
    path_matches_entry,
)

router = APIRouter(prefix="/api/panel", tags=["panel"])


@router.get("/gate", response_model=PanelGateOut)
def panel_gate(
    path: str = Query(..., min_length=1, max_length=500),
    db: Session = Depends(get_db),
) -> PanelGateOut:
    row = get_or_create_panel_settings(db)
    if not gate_is_enabled(db):
        return PanelGateOut(allowed=True, entry_path=None)
    if path_matches_entry(path, row.entry_path):
        return PanelGateOut(allowed=True, entry_path=row.entry_path)
    return PanelGateOut(allowed=False, entry_path=None)
