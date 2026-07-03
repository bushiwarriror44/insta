"""Public health probe (no auth)."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import HealthOut
from app.config import settings

router = APIRouter(prefix="/api/health", tags=["health"])


__VERSION__ = "0.2.0"


@router.get("", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(
        ok=True,
        version=__VERSION__,
        auth_required=bool(settings.admin_token),
    )
