"""Signed image refs for Qubax image-to-video (no bearer auth)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.routes.videos import IMAGE_EXTENSIONS, _named_file
from app.config import Settings, get_settings
from app.services.media_links import verify

router = APIRouter(prefix="/api/qubax/refs", tags=["qubax-refs"])


@router.get("/{filename}")
def serve_ref(
    filename: str,
    expires: int = Query(...),
    sig: str = Query(...),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    if not verify(filename, expires, sig, settings=settings):
        raise HTTPException(status_code=403, detail="ссылка недействительна или истекла")
    path = _named_file(settings.video_source_dir, filename)
    if path is None:
        path = _named_file(settings.media_dir, filename)
    if path is None or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="не найдено")
    media = "image/jpeg"
    if path.suffix.lower() == ".png":
        media = "image/png"
    elif path.suffix.lower() == ".webp":
        media = "image/webp"
    return FileResponse(path, media_type=media)
