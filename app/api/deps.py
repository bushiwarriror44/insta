"""FastAPI dependencies: DB session and auth."""
from __future__ import annotations

from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Bearer-token check.

    If ``settings.admin_token`` is empty/None the API runs in open mode
    (intended only for localhost / VPN). Otherwise we require a matching
    ``Authorization: Bearer <token>`` header.
    """
    expected = settings.admin_token
    if not expected:
        return

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = authorization.split(" ", 1)[1].strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


AuthDep = Depends(require_token)


def verify_ws_token(authorization: Optional[str], token_query: Optional[str] = None) -> bool:
    """Return True when the Bearer/?token= value matches ``settings.admin_token``."""
    expected = settings.admin_token
    if not expected:
        return True

    provided: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    elif token_query:
        provided = token_query.strip()

    return bool(provided and provided == expected)
