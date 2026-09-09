"""HMAC tickets for files an <img> or <video> fetches without a bearer token."""

from __future__ import annotations

import hmac
import secrets
import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote

from app.config import Settings, get_settings

SECRET_FILENAME = "media_url_secret"


def _secret(settings: Settings) -> str:
    if settings.media_url_secret:
        return settings.media_url_secret
    path = Path(settings.data_dir) / SECRET_FILENAME
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    generated = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generated, encoding="utf-8")
    return generated


def sign(filename: str, expires_at: int, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    message = f"{filename}:{expires_at}".encode()
    return hmac.new(_secret(settings).encode(), message, sha256).hexdigest()


def verify(
    filename: str,
    expires_at: int,
    signature: str,
    *,
    settings: Settings | None = None,
    now: int | None = None,
) -> bool:
    now = now if now is not None else int(time.time())
    if expires_at < now:
        return False
    return hmac.compare_digest(sign(filename, expires_at, settings), signature)


def relative_url(filename: str, *, prefix: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    expires_at = int(time.time()) + settings.media_link_ttl_seconds
    signature = sign(filename, expires_at, settings)
    return f"{prefix}/{quote(filename)}?expires={expires_at}&sig={signature}"
