"""Save a generated MP4 from an HTTP response or URL."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.generation.base import GenerationError

MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_DETAIL_LIMIT = 400


def _server_detail(response: httpx.Response) -> str:
    """Short reason from a failed render response. Skips Salad HTML error pages."""
    text = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            text = detail
        elif isinstance(detail, list) and detail:
            text = " ".join(str(item) for item in detail)
    if not text:
        raw = (response.text or "").strip()
        if not raw or raw.startswith("<") or "Service Unavailable" in raw:
            return ""
        text = raw
    text = " ".join(text.split())
    if len(text) > _DETAIL_LIMIT:
        return text[: _DETAIL_LIMIT - 1] + "…"
    return text


def raise_http(response: httpx.Response, name: str, stage: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code in (401, 403):
        raise GenerationError(f"{name}: отклонены учётные данные ({stage})")
    if response.status_code == 404:
        raise GenerationError(f"{name}: {stage} вернул 404", retryable=True)
    if response.status_code == 429:
        raise GenerationError(f"{name}: лимит запросов на {stage}", retryable=True)
    if response.status_code >= 500:
        message = f"{name}: ошибка сервера {response.status_code} ({stage})"
        detail = _server_detail(response)
        if detail:
            message = f"{message}: {detail}"
        raise GenerationError(message, retryable=True)
    raise GenerationError(f"{name}: {stage} завершился с кодом {response.status_code}")


def write_bytes(data: bytes, destination: Path) -> Path:
    if not data:
        raise GenerationError("провайдер вернул пустое видео", retryable=True)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise GenerationError("сгенерированное видео слишком большое")
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
                        raise GenerationError("сгенерированное видео слишком большое")
                    out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if written == 0:
        destination.unlink(missing_ok=True)
        raise GenerationError(f"{name} вернул пустое видео", retryable=True)
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
            raise GenerationError(f"{name} вернул некорректный JSON", retryable=True) from exc
        url = video_url_from(body)
        if not url:
            raise GenerationError(f"{name} не вернул url видео", retryable=True)
        return download_url(client, url, destination, name=name)
    if response.content[:4] == b"\x00\x00\x00" or response.content[4:8] == b"ftyp":
        return write_bytes(response.content, destination)
    raise GenerationError(f"{name} не вернул видео", retryable=True)


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
