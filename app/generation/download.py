"""Save a generated MP4 from an HTTP response or URL."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.generation.base import GenerationError

MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


def raise_http(response: httpx.Response, name: str, stage: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code in (401, 403):
        raise GenerationError(f"{name} rejected the credentials ({stage})")
    if response.status_code == 404:
        raise GenerationError(f"{name} {stage} returned 404", retryable=True)
    if response.status_code == 429:
        raise GenerationError(f"{name} rate limited the {stage}", retryable=True)
    if response.status_code >= 500:
        raise GenerationError(
            f"{name} server error {response.status_code} ({stage})",
            retryable=True,
        )
    raise GenerationError(f"{name} {stage} failed: {response.status_code}")


def write_bytes(data: bytes, destination: Path) -> Path:
    if not data:
        raise GenerationError("provider returned an empty video", retryable=True)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise GenerationError("generated video is implausibly large")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


def download_url(
    client: httpx.Client,
    url: str,
    destination: Path,
    *,
    name: str,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with client.stream("GET", url, timeout=300) as response:
            raise_http(response, name, "download")
            with destination.open("wb") as out:
                for chunk in response.iter_bytes(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise GenerationError("generated video is implausibly large")
                    out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if written == 0:
        destination.unlink(missing_ok=True)
        raise GenerationError(f"{name} returned an empty video", retryable=True)
    return destination


def save_response(
    client: httpx.Client,
    response: httpx.Response,
    destination: Path,
    *,
    name: str,
) -> Path:
    """Persist MP4 bytes, or follow a JSON url field."""
    raise_http(response, name, "generate")
    ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype in {"video/mp4", "application/octet-stream", "binary/octet-stream"}:
        return write_bytes(response.content, destination)
    if ctype.endswith("+json") or ctype == "application/json" or ctype == "text/json":
        try:
            body = response.json()
        except ValueError as exc:
            raise GenerationError(f"{name} returned invalid JSON", retryable=True) from exc
        url = video_url_from(body)
        if not url:
            raise GenerationError(f"{name} returned no video url", retryable=True)
        return download_url(client, url, destination, name=name)
    if response.content[:4] == b"\x00\x00\x00" or response.content[4:8] == b"ftyp":
        return write_bytes(response.content, destination)
    raise GenerationError(f"{name} did not return a video", retryable=True)


def video_url_from(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    for key in ("url", "video_url"):
        value = body.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    video = body.get("video")
    if isinstance(video, str) and video.startswith("http"):
        return video
    if isinstance(video, dict):
        nested = video.get("url")
        if isinstance(nested, str) and nested.startswith("http"):
            return nested
    output = body.get("output")
    if isinstance(output, str) and output.startswith("http"):
        return output
    if isinstance(output, dict):
        nested = output.get("url")
        if isinstance(nested, str) and nested.startswith("http"):
            return nested
    return ""
