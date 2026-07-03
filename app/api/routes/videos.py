"""Media upload + listing endpoints."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import AuthDep
from app.api.schemas import UploadOut, VideoOut
from app.config import settings

router = APIRouter(prefix="/api/videos", tags=["videos"], dependencies=[AuthDep])


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _safe_name(name: str) -> str:
    base = Path(name).name
    base = SAFE_NAME_RE.sub("_", base)
    return base or "upload.mp4"


def media_type_for_name(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    raise ValueError(f"Unsupported extension: {suffix}")


def _resolve_source_file(filename: str) -> Path:
    safe = _safe_name(filename)
    if safe != filename:
        raise HTTPException(status_code=404, detail="File not found")
    target = settings.video_source_dir / safe
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=404, detail="File not found")
    return target


def _duration_for_path(path: Path, media_type: str) -> Optional[float]:
    if media_type != "video":
        return None
    try:
        from app.video.uniquifier import probe

        meta = probe(path)
        return round(meta.duration_sec, 2) if meta.duration_sec > 0 else None
    except Exception:
        return None


def _video_out_from_path(path: Path) -> VideoOut:
    st = path.stat()
    media_type = media_type_for_name(path.name)
    return VideoOut(
        filename=path.name,
        size_bytes=st.st_size,
        modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        media_type=media_type,
        duration_sec=_duration_for_path(path, media_type),
    )


@router.get("", response_model=List[VideoOut])
def list_videos() -> List[VideoOut]:
    src: Path = settings.video_source_dir
    if not src.exists():
        return []
    out: List[VideoOut] = []
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        out.append(_video_out_from_path(p))
    return sorted(out, key=lambda v: v.modified_at, reverse=True)


@router.get("/{filename}")
def get_video(filename: str) -> FileResponse:
    target = _resolve_source_file(filename)
    content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=target,
        media_type=content_type,
        filename=target.name,
    )


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def upload_video(file: UploadFile = File(...)) -> UploadOut:
    filename = _safe_name(file.filename or "upload.mp4")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported extension: {suffix}")
    media_type = media_type_for_name(filename)

    src: Path = settings.video_source_dir
    src.mkdir(parents=True, exist_ok=True)
    dst = src / filename
    if dst.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dst = src / f"{Path(filename).stem}-{ts}{suffix}"

    max_bytes = settings.upload_max_mb * 1024 * 1024
    written = 0
    try:
        with dst.open("wb") as fh:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    dst.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {settings.upload_max_mb} MB limit",
                    )
                fh.write(chunk)
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    return UploadOut(
        filename=dst.name,
        size_bytes=written,
        media_type=media_type,
        duration_sec=_duration_for_path(dst, media_type),
    )


@router.delete("/{filename}")
def delete_video(filename: str) -> dict[str, bool]:
    target = _resolve_source_file(filename)
    try:
        target.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}
