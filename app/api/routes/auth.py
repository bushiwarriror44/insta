"""Auth identity endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, AuthPrincipal, get_db, require_token
from app.api.schemas import AuthMeOut
from app.panel.settings_store import auth_is_required

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[AuthDep])


@router.get("/me", response_model=AuthMeOut)
def auth_me(
    principal: AuthPrincipal = Depends(require_token),
    db: Session = Depends(get_db),
) -> AuthMeOut:
    if not auth_is_required(db):
        return AuthMeOut(role=None, label=None)
    return AuthMeOut(role=principal.role, label=principal.label)
