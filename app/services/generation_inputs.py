"""Resolve generation_jobs.reference_json into paths on disk."""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.api.routes.videos import media_type_for_name
from app.config import Settings, get_settings
from app.db.models import GenerationJob, MediaAsset
from app.services.media import MediaError, asset_media_path, resolve as resolve_media_path
from app.generation.base import (
    GenerationError,
    GenerationReference,
    GenerationRequest,
    INPUT_MODE_I2V,
    INPUT_MODE_SLIDESHOW,
    INPUT_MODE_TEXT,
    INPUT_MODE_V2V,
    REF_END_IMAGE,
    REF_MOTION_VIDEO,
    REF_START_IMAGE,
    REF_STYLE_IMAGE,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
V2V_MAX_DURATION_SEC = 15.0

_ROLE_IMAGE = frozenset({REF_START_IMAGE, REF_END_IMAGE, REF_STYLE_IMAGE})


def _safe_library_name(name: str) -> str:
    from app.api.routes.videos import _safe_name

    return _safe_name(name)


def parse_reference_specs(raw: str | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"reference_json: {exc}") from exc
    if isinstance(parsed, dict):
        return [parsed]
    if not isinstance(parsed, list):
        raise GenerationError("reference_json должен быть объектом или массивом")
    return [item for item in parsed if isinstance(item, dict)]


def infer_input_mode(
    explicit: str | None,
    specs: list[dict[str, Any]],
) -> str:
    mode = (explicit or "").strip().lower()
    if mode in (INPUT_MODE_I2V, INPUT_MODE_V2V, INPUT_MODE_SLIDESHOW):
        return mode
    inferred = INPUT_MODE_TEXT
    for spec in specs:
        role = str(spec.get("role") or REF_START_IMAGE).strip()
        if role == REF_MOTION_VIDEO:
            inferred = INPUT_MODE_V2V
            break
        if role in _ROLE_IMAGE:
            inferred = INPUT_MODE_I2V
    if inferred != INPUT_MODE_TEXT:
        return inferred
    return mode if mode else INPUT_MODE_TEXT


def build_reference_json(
    *,
    reference_asset_id: int | None = None,
    reference_filename: str | None = None,
    role: str = REF_START_IMAGE,
) -> list[dict[str, Any]]:
    if reference_asset_id is not None:
        return [{"role": role, "asset_id": int(reference_asset_id)}]
    name = (reference_filename or "").strip()
    if name:
        return [{"role": role, "filename": _safe_library_name(name)}]
    return []


def _mime_for_path(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image/jpeg" if suffix in {".jpg", ".jpeg"} else f"image/{suffix.lstrip('.')}"
    if suffix in VIDEO_EXTENSIONS:
        return "video/mp4"
    return "application/octet-stream"


def _resolve_spec_path(
    session: Session,
    spec: dict[str, Any],
    settings: Settings,
) -> Path:
    asset_id = spec.get("asset_id")
    if asset_id is not None:
        asset = session.get(MediaAsset, int(asset_id))
        if asset is None or asset.file_removed_at is not None:
            raise GenerationError(f"asset_id={asset_id} не найден")
        try:
            return asset_media_path(settings.media_dir, asset)
        except MediaError as exc:
            raise GenerationError(str(exc)) from exc
    filename = spec.get("filename")
    if filename:
        safe = _safe_library_name(str(filename))
        try:
            path = resolve_media_path(settings.video_source_dir, safe)
        except MediaError as exc:
            raise GenerationError(str(exc)) from exc
        if not path.is_file():
            raise GenerationError(f"файл библиотеки {safe!r} не найден")
        return path
    raise GenerationError("элемент reference_json без asset_id и filename")


def _check_size(path: Path, settings: Settings) -> None:
    max_bytes = settings.upload_max_mb * 1024 * 1024
    size = path.stat().st_size
    if size > max_bytes:
        raise GenerationError(
            f"референс {path.name} больше лимита {settings.upload_max_mb} MB",
            retryable=False,
        )


def resolve_generation_inputs(
    session: Session,
    job: GenerationJob,
    settings: Settings | None = None,
) -> GenerationRequest:
    settings = settings or get_settings()
    specs = parse_reference_specs(job.reference_json)
    mode = infer_input_mode(job.input_mode, specs)
    references: list[GenerationReference] = []
    for spec in specs:
        role = str(spec.get("role") or REF_START_IMAGE).strip()
        path = _resolve_spec_path(session, spec, settings)
        _check_size(path, settings)
        suffix = path.suffix.lower()
        if role == REF_MOTION_VIDEO:
            if suffix not in VIDEO_EXTENSIONS:
                raise GenerationError(f"motion_video: нужен mp4/mov, не {suffix}")
            from app.video.reference_trim import ensure_video_reference

            path = ensure_video_reference(path, settings, max_duration_s=V2V_MAX_DURATION_SEC)
        elif role in _ROLE_IMAGE:
            if suffix not in IMAGE_EXTENSIONS:
                try:
                    if media_type_for_name(path.name) != "image":
                        raise GenerationError(f"{role}: нужен jpg/png/webp")
                except ValueError as exc:
                    raise GenerationError(str(exc)) from exc
        references.append(
            GenerationReference(role=role, path=path, mime=_mime_for_path(path))
        )

    if mode == INPUT_MODE_I2V and not any(r.role in _ROLE_IMAGE for r in references):
        raise GenerationError("image_to_video: нужен start_image (asset_id или filename)")
    if mode == INPUT_MODE_V2V and not any(r.role == REF_MOTION_VIDEO for r in references):
        raise GenerationError("video_to_video: нужен motion_video")
    if mode == INPUT_MODE_SLIDESHOW and not any(r.role in _ROLE_IMAGE for r in references):
        raise GenerationError("image_slideshow: нужно хотя бы одно изображение")

    return GenerationRequest(
        prompt=job.prompt,
        negative_prompt=job.negative_prompt or "",
        duration_s=job.duration_s,
        width=job.width,
        height=job.height,
        seed=job.seed,
        mode=mode,
        references=references,
    )


def apply_job_reference_fields(
    job: GenerationJob,
    *,
    input_mode: str | None = None,
    reference_json: str | list[dict[str, Any]] | None = None,
    reference_asset_id: int | None = None,
    reference_filename: str | None = None,
    reference_filenames: list[str] | None = None,
    reference_role: str = REF_START_IMAGE,
) -> None:
    specs: list[dict[str, Any]] = []
    names = [name.strip() for name in (reference_filenames or []) if name and name.strip()]
    if names:
        seen: set[str] = set()
        for name in names:
            for spec in build_reference_json(reference_filename=name, role=reference_role):
                key = str(spec.get("filename") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                specs.append(spec)
    elif reference_json is not None:
        specs = parse_reference_specs(reference_json)
    if not specs:
        specs = build_reference_json(
            reference_asset_id=reference_asset_id,
            reference_filename=reference_filename,
            role=reference_role,
        )
    job.input_mode = infer_input_mode(input_mode, specs)
    job.reference_json = json.dumps(specs, ensure_ascii=False) if specs else None


def ensure_job_references(session: Session, job: GenerationJob, settings: Settings | None = None) -> None:
    """Reject a missing library file before the job is queued."""
    resolve_generation_inputs(session, job, settings)


def backend_supports_request(backend, request: GenerationRequest) -> bool:
    if request.mode == INPUT_MODE_TEXT:
        return bool(getattr(backend, "supports_text", True))
    if request.mode == INPUT_MODE_I2V:
        return bool(getattr(backend, "supports_i2v", False))
    if request.mode == INPUT_MODE_V2V:
        return bool(getattr(backend, "supports_v2v", False))
    if request.mode == INPUT_MODE_SLIDESHOW:
        return bool(getattr(backend, "supports_slideshow", False))
    return False
