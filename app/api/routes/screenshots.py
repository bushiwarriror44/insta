"""Signed delivery of screenshots the assistant's browser tool took."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.services.media import MediaError, resolve
from app.services.media_links import verify

router = APIRouter(prefix="/api/screenshots", tags=["screenshots"])


@router.get("/{filename}")
def serve(
    filename: str,
    expires: int = Query(...),
    sig: str = Query(...),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    if not verify(filename, expires, sig, settings=settings):
        raise HTTPException(status_code=403, detail="ссылка недействительна или истекла")
    try:
        path = resolve(settings.screenshots_dir, filename)
    except MediaError as exc:
        raise HTTPException(status_code=403, detail="ссылка недействительна или истекла") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="не найдено")
    return FileResponse(path, media_type="image/png")
