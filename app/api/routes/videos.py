"""Media upload + listing endpoints."""
from __future__ import annotations

import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.deps import AuthDep
from app.api.schemas import MediaArchiveIn, UploadOut, VideoOut
from app.config import settings
from app.video.image_compress import compress_image_file

router = APIRouter(prefix="/api/videos", tags=["videos"], dependencies=[AuthDep])


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS | AUDIO_EXTENSIONS
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
ARCHIVE_MAX_FILES = 100

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
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
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    raise ValueError(f"Неподдерживаемое расширение: {suffix}")


def _named_file(directory: Path, filename: str) -> Path | None:
    safe = _safe_name(filename)
    if safe != filename:
        return None
    root = directory.resolve()
    target = (directory / safe).resolve()
    if target.parent != root:
        return None
    if not target.is_file():
        return None
    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        return None
    return target


def _resolve_source_file(filename: str) -> Path:
    upload = _named_file(settings.video_source_dir, filename)
    if upload is not None:
        return upload
    generated = _named_file(settings.media_dir, filename)
    if generated is not None:
        return generated
    raise HTTPException(status_code=404, detail="Файл не найден")


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


def _unlink_quiet(path: str) -> None:
    Path(path).unlink(missing_ok=True)


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


@router.post("/archive")
def archive_videos(payload: MediaArchiveIn) -> FileResponse:
    names: list[str] = []
    seen: set[str] = set()
    for name in payload.filenames:
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        raise HTTPException(status_code=400, detail="Не указаны файлы для архива")
    if len(names) > ARCHIVE_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Слишком много файлов (макс. {ARCHIVE_MAX_FILES})",
        )

    paths = [_resolve_source_file(name) for name in names]
    total = sum(p.stat().st_size for p in paths)
    max_bytes = settings.upload_max_mb * 1024 * 1024
    if total > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Архив превышает лимит {settings.upload_max_mb} МБ",
        )

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for path in paths:
                zf.write(path, arcname=path.name)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        path=tmp_path,
        media_type="application/zip",
        filename=f"media-{stamp}.zip",
        background=BackgroundTask(_unlink_quiet, str(tmp_path)),
    )


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
def upload_video(
    file: UploadFile = File(...),
    compress: bool = Form(True),
) -> UploadOut:
    filename = _safe_name(file.filename or "upload.mp4")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемое расширение: {suffix}")
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
                        detail=f"Файл превышает лимит {settings.upload_max_mb} МБ",
                    )
                fh.write(chunk)
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    if media_type == "image" and compress:
        try:
            dst = compress_image_file(
                dst,
                max_edge=settings.image_compress_max_edge,
                quality=settings.image_compress_quality,
            )
            written = dst.stat().st_size
        except Exception as exc:
            dst.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"Не удалось сжать изображение: {exc}",
            ) from exc

    return UploadOut(
        filename=dst.name,
        size_bytes=written,
        media_type=media_type,
        duration_sec=_duration_for_path(dst, media_type),
    )


@router.delete("/{filename}")
def delete_video(filename: str) -> dict[str, bool]:
    target = _named_file(settings.video_source_dir, filename)
    if target is None:
        if _named_file(settings.media_dir, filename) is not None:
            raise HTTPException(
                status_code=400,
                detail="Сгенерированный файл удаляется со страницы рендеров",
            )
        raise HTTPException(status_code=404, detail="Файл не найден")
    try:
        target.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}
