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
