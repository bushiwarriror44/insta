"""Derive the public panel/API origin from an incoming HTTP request."""
from __future__ import annotations

from fastapi import Request


def public_origin(request: Request) -> str:
    """Prefer forwarded headers when the panel sits behind a reverse proxy."""
    forwarded = (request.headers.get("x-forwarded-host") or "").strip()
    if forwarded:
        proto = (request.headers.get("x-forwarded-proto") or "https").split(",")[0].strip()
        host = forwarded.split(",")[0].strip()
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")
