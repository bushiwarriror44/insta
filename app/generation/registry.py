"""Lookup for the configured video generation backend."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.generation.base import VideoBackend
from app.generation.chain import ChainVideoBackend
from app.generation.fal import FalVideoBackend
from app.generation.hfspace import HfSpaceVideoBackend
from app.generation.huggingface import HuggingFaceVideoBackend
from app.generation.local import LocalVideoBackend
from app.generation.pollinations import PollinationsVideoBackend
from app.generation.slideshow import SlideshowVideoBackend

DEFAULT_CHAIN = "fal,huggingface,pollinations,local,hfspace"

_BACKENDS: dict[str, type[VideoBackend]] = {
    FalVideoBackend.name: FalVideoBackend,
    HuggingFaceVideoBackend.name: HuggingFaceVideoBackend,
    PollinationsVideoBackend.name: PollinationsVideoBackend,
    LocalVideoBackend.name: LocalVideoBackend,
    HfSpaceVideoBackend.name: HfSpaceVideoBackend,
    SlideshowVideoBackend.name: SlideshowVideoBackend,
    ChainVideoBackend.name: ChainVideoBackend,
}


def parse_chain(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    raw = (settings.video_backend_chain or DEFAULT_CHAIN).replace(";", ",")
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name and name not in names and name in _BACKENDS and name != ChainVideoBackend.name:
            names.append(name)
    return names


def get_backend(name: str | None = None, settings: Settings | None = None) -> VideoBackend:
    settings = settings or get_settings()
    key = (name or settings.video_backend or ChainVideoBackend.name).strip().lower()
    try:
        backend = _BACKENDS[key]
    except KeyError:
        raise NotImplementedError(f"no video backend named {key!r}") from None
    return backend(settings)


def available_backends() -> list[str]:
    return [ChainVideoBackend.name, *parse_chain(), *[
        name for name in sorted(_BACKENDS) if name not in {ChainVideoBackend.name, *parse_chain()}
    ]]


def describe_backends(settings: Settings | None = None) -> list[dict[str, object]]:
    settings = settings or get_settings()
    rows = []
    for name in available_backends():
        engine = get_backend(name, settings)
        rows.append(
            {
                "name": engine.name,
                "healthy": engine.healthcheck(),
                "licence": engine.model_licence,
                "experimental": bool(engine.experimental),
                "detail": engine.health_detail(),
                "supports_i2v": bool(getattr(engine, "supports_i2v", False)),
                "supports_v2v": bool(getattr(engine, "supports_v2v", False)),
                "supports_slideshow": bool(getattr(engine, "supports_slideshow", False)),
            }
        )
    return rows
