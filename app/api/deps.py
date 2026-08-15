"""FastAPI dependencies: DB session and auth."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Literal, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.config import settings
from app.db import PanelOperator, PanelSettings, SessionLocal
from app.panel.settings_store import auth_is_required, get_or_create_panel_settings


Role = Literal["owner", "operator"]


@dataclass(frozen=True)
class AuthPrincipal:
    role: Role
    operator_id: Optional[int] = None
    label: Optional[str] = None


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


def _find_active_operator(db: Session, password: str) -> Optional[PanelOperator]:
    rows = db.scalars(
        select(PanelOperator).where(PanelOperator.revoked_at.is_(None))
    ).all()
    for row in rows:
        if verify_password(password, row.password_hash):
            return row
    return None


def _master_password_ok(db: Session, provided: str) -> bool:
    row = db.get(PanelSettings, 1)
    if row is None or not row.master_password_hash:
        return False
    return verify_password(provided, row.master_password_hash)


def _env_token_ok(provided: str) -> bool:
    expected = settings.admin_token
    if not expected:
        return False
    return hmac.compare_digest(provided, expected)


def verify_owner_password(db: Session, password: str) -> bool:
    """True if password matches env ADMIN_TOKEN and/or DB master hash."""
    return _env_token_ok(password) or _master_password_ok(db, password)


def resolve_principal(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthPrincipal:
    """Resolve Bearer into owner/operator, or synthetic owner in open mode."""
    get_or_create_panel_settings(db)

    if not auth_is_required(db):
        return AuthPrincipal(role="owner")

    provided = _extract_bearer(authorization)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация: заголовок Authorization Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if verify_owner_password(db, provided):
        return AuthPrincipal(role="owner", label="master")

    operator = _find_active_operator(db, provided)
    if operator is not None:
        operator.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return AuthPrincipal(
            role="operator",
            operator_id=operator.id,
            label=operator.label,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный токен",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_owner(principal: AuthPrincipal = Depends(resolve_principal), db: Session = Depends(get_db)) -> AuthPrincipal:
    if not auth_is_required(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Управление настройками недоступно: задайте ADMIN_TOKEN или мастер-пароль",
        )
    if principal.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только владелец может управлять доступами и настройками",
        )
    return principal


def require_token(
    principal: AuthPrincipal = Depends(resolve_principal),
) -> AuthPrincipal:
    return principal


AuthDep = Depends(require_token)
OwnerDep = Depends(require_owner)


def verify_ws_token(
    authorization: Optional[str],
    token_query: Optional[str] = None,
    *,
    db: Optional[Session] = None,
) -> bool:
    """Return True when Bearer/?token= is master or an active operator password."""
    own_session = False
    session = db
    if session is None:
        session = SessionLocal()
        own_session = True
    try:
        get_or_create_panel_settings(session)
        if not auth_is_required(session):
            return True

        provided: str | None = None
        if authorization and authorization.lower().startswith("bearer "):
            provided = authorization.split(" ", 1)[1].strip()
        elif token_query:
            provided = token_query.strip()

        if not provided:
            return False

        if verify_owner_password(session, provided):
            return True
        return _find_active_operator(session, provided) is not None
    finally:
        if own_session:
            session.close()
