"""Lookup for the configured video generation backend."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.generation.base import VideoBackend
from app.generation.fal import FalVideoBackend

_BACKENDS: dict[str, type[VideoBackend]] = {
    FalVideoBackend.name: FalVideoBackend,
}


def get_backend(name: str = "fal", settings: Settings | None = None) -> VideoBackend:
    try:
        backend = _BACKENDS[name]
    except KeyError:
        raise NotImplementedError(f"no video backend named {name!r}") from None
    return backend(settings or get_settings())


def available_backends() -> list[str]:
    return sorted(_BACKENDS)
