"""Owner-only panel settings (entry path + master password)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import OwnerDep, get_db, verify_owner_password
from app.api.schemas import (
    PanelEntryPathUpdateIn,
    PanelMasterPasswordUpdateIn,
    PanelSettingsOut,
)
from app.auth.passwords import hash_password
from app.panel.settings_store import get_or_create_panel_settings, validate_entry_path

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[OwnerDep])


@router.get("", response_model=PanelSettingsOut)
def get_settings(db: Session = Depends(get_db)) -> PanelSettingsOut:
    row = get_or_create_panel_settings(db)
    return PanelSettingsOut(
        entry_path=row.entry_path,
        master_password_set=bool(row.master_password_hash),
    )


@router.put("/entry-path", response_model=PanelSettingsOut)
def update_entry_path(
    payload: PanelEntryPathUpdateIn,
    db: Session = Depends(get_db),
) -> PanelSettingsOut:
    if not verify_owner_password(db, payload.current_password):
        raise HTTPException(status_code=401, detail="Неверный текущий пароль")
    try:
        path = validate_entry_path(payload.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = get_or_create_panel_settings(db)
    row.entry_path = path
    db.commit()
    db.refresh(row)
    return PanelSettingsOut(
        entry_path=row.entry_path,
        master_password_set=bool(row.master_password_hash),
    )


@router.put("/master-password", response_model=PanelSettingsOut)
def update_master_password(
    payload: PanelMasterPasswordUpdateIn,
    db: Session = Depends(get_db),
) -> PanelSettingsOut:
    if not verify_owner_password(db, payload.current_password):
        raise HTTPException(status_code=401, detail="Неверный текущий пароль")
    new_pw = payload.new_password.strip()
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Новый пароль слишком короткий")

    row = get_or_create_panel_settings(db)
    row.master_password_hash = hash_password(new_pw)
    db.commit()
    db.refresh(row)
    return PanelSettingsOut(
        entry_path=row.entry_path,
        master_password_set=True,
    )
