"""Storage and inspection of video assets.

Uploaded filenames are never trusted as paths: the stored name is
generated here and only the extension is carried over from the client,
so a crafted name cannot escape the media directory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.db.models import AssetKind, AssetSource, MediaAsset

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
#: A soundtrack is an asset like any other: same storage, same signed
#: links, same library.
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


class MediaError(ValueError):
    pass


@dataclass(slots=True)
class Probe:
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None


def safe_extension(client_filename: str) -> str:
    ext = Path(client_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise MediaError(
            f"unsupported extension {ext or '(none)'}; "
            f"allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def storage_name(client_filename: str) -> str:
    """A generated, collision-free name — never the client's own."""
    return f"{uuid.uuid4().hex}{safe_extension(client_filename)}"


def resolve(media_dir: Path, filename: str) -> Path:
    """Resolve a stored filename inside `media_dir`, refusing to escape it."""
    media_dir = media_dir.resolve()
    candidate = (media_dir / filename).resolve()
    if candidate.parent != media_dir:
        raise MediaError("filename escapes the media directory")
    return candidate


def asset_media_path(media_dir: Path, asset: MediaAsset) -> Path:
    """Path to a library asset on disk, or `MediaError` if unavailable."""
    if asset.file_removed_at is not None:
        raise MediaError(f"asset_id={asset.id} удалён с диска")
    path = resolve(media_dir, asset.filename)
    if not path.is_file():
        raise MediaError(f"файл asset {asset.id} отсутствует на диске")
    return path


def probe_video(path: Path) -> Probe:
    """Read duration and dimensions with ffprobe, tolerating its absence."""
    if shutil.which("ffprobe") is None:
        return Probe()

    try:
        raw = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
        data = json.loads(raw)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return Probe()

    stream = (data.get("streams") or [{}])[0]
    duration = (data.get("format") or {}).get("duration")
    return Probe(
        duration_s=float(duration) if duration else None,
        width=stream.get("width"),
        height=stream.get("height"),
    )


def save_upload(
    media_dir: Path,
    client_filename: str,
    stream: BinaryIO,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> MediaAsset:
    """Write an upload to disk and build the matching `MediaAsset`."""
    media_dir.mkdir(parents=True, exist_ok=True)
    name = storage_name(client_filename)
    destination = media_dir / name

    written = 0
    try:
        with destination.open("wb") as out:
            while chunk := stream.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise MediaError(f"upload exceeds {max_bytes // (1024 * 1024)} MB")
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    if written == 0:
        destination.unlink(missing_ok=True)
        raise MediaError("uploaded file is empty")

    kind = (
        AssetKind.audio
        if destination.suffix.lower() in AUDIO_EXTENSIONS
        else AssetKind.video
    )
    # ffprobe reads a soundtrack as readily as a clip, and a track's
    # length decides whether it loops under the post — worth knowing
    # before the render rather than after.
    probe = probe_video(destination)
    return MediaAsset(
        filename=name,
        kind=kind,
        source=AssetSource.upload,
        # The stored name is a uuid. The one the operator typed is the
        # only thing anyone — or any model — can recognise it by.
        label=Path(client_filename).stem[:120] if client_filename else "",
        duration_s=probe.duration_s,
        width=probe.width if kind is AssetKind.video else None,
        height=probe.height if kind is AssetKind.video else None,
    )


def delete_file(media_dir: Path, filename: str) -> None:
    resolve(media_dir, filename).unlink(missing_ok=True)


def resolve_library_media_path(path: Path, library_dir: Path) -> Path:
    """Absolute path must be a regular file under the upload library root."""
    resolved = path.resolve()
    root = library_dir.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise MediaError("file must be under upload library (video_source_dir)") from None
    if not resolved.is_file():
        raise MediaError("File not found")
    return resolved
