"""Owner/open-mode notebook on the Administration page."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import DocsOwnerDep, get_db
from app.api.schemas import AdminNotesIn, AdminNotesOut
from app.db import PanelSettings
from app.panel.settings_store import get_or_create_panel_settings

router = APIRouter(
    prefix="/api/admin-notes",
    tags=["admin-notes"],
    dependencies=[DocsOwnerDep],
)


def _payload(row: PanelSettings) -> AdminNotesOut:
    return AdminNotesOut(content=row.admin_notes or "", updated_at=row.updated_at)


@router.get("", response_model=AdminNotesOut)
def read_notes(db: Session = Depends(get_db)) -> AdminNotesOut:
    return _payload(get_or_create_panel_settings(db))


@router.put("", response_model=AdminNotesOut)
def write_notes(payload: AdminNotesIn, db: Session = Depends(get_db)) -> AdminNotesOut:
    row = get_or_create_panel_settings(db)
    row.admin_notes = payload.content
    db.commit()
    db.refresh(row)
    return _payload(row)
