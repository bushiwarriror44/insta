"""Ollama, seen from the panel."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from app.config import Settings, get_settings
from app.services.http import client as http_client

MIN_CONTEXT = 4096
MAX_CONTEXT = 40960
LOAD_TIMEOUT = 300.0
UNLOAD_TIMEOUT = 60.0
UNLOAD_WAIT = 30.0


class RuntimeError_(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Loaded:
    name: str
    context: int
    size_bytes: int = 0


@dataclass
class Runtime:
    reachable: bool
    base_url: str
    models: list[str] = field(default_factory=list)
    loaded: list[Loaded] = field(default_factory=list)
    detail: str | None = None

    def context_of(self, model: str) -> int | None:
        for one in self.loaded:
            if one.name == model:
                return one.context
        return None


def native(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    return trimmed[: -len("/v1")] if trimmed.endswith("/v1") else trimmed


def _model_name(entry: dict) -> str:
    return str(entry.get("model") or entry.get("name") or "")


def probe(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    root = native(settings.agent_base_url)
    if not root:
        return Runtime(reachable=False, base_url="", detail="AGENT_BASE_URL не задан")

    try:
        with http_client(settings, timeout=10.0) as client:
            tags = client.get(f"{root}/api/tags")
            running = client.get(f"{root}/api/ps")
    except httpx.RequestError as exc:
        return Runtime(reachable=False, base_url=root, detail=f"не отвечает: {exc}")

    if tags.status_code >= 400:
        return Runtime(reachable=False, base_url=root, detail=f"ответил {tags.status_code}")

    return Runtime(
        reachable=True,
        base_url=root,
        models=sorted(_model_name(m) for m in _models(tags)),
        loaded=[
            Loaded(
                name=_model_name(m),
                context=int(m.get("context_length") or 0),
                size_bytes=int(m.get("size") or 0),
            )
            for m in _models(running)
        ],
    )


def unload_loaded(settings: Settings | None = None) -> list[str]:
    """Drop every model sitting in VRAM so a local video job can use the card.

    Failures here must not abort the render: a dead Ollama is already empty.
    """
    settings = settings or get_settings()
    root = native(settings.agent_base_url)
    if not root:
        return []
    seen = probe(settings)
    if not seen.reachable:
        return []
    names = [one.name for one in seen.loaded if one.name]
    if not names:
        return []
    try:
        with http_client(settings, timeout=UNLOAD_TIMEOUT) as client:
            for name in names:
                client.post(
                    f"{root}/api/generate",
                    json={"model": name, "keep_alive": 0},
                )
    except httpx.RequestError:
        return names
    deadline = time.monotonic() + UNLOAD_WAIT
    while time.monotonic() < deadline:
        after = probe(settings)
        if not after.loaded:
            break
        time.sleep(0.4)
    return names


def load_with_context(model: str, context: int, settings: Settings | None = None) -> Loaded:
    settings = settings or get_settings()
    if not MIN_CONTEXT <= context <= MAX_CONTEXT:
        raise RuntimeError_(
            f"контекст должен быть от {MIN_CONTEXT} до {MAX_CONTEXT}, а не {context}"
        )
    root = native(settings.agent_base_url)
    if not root:
        raise RuntimeError_("AGENT_BASE_URL не задан")
    try:
        with http_client(settings, timeout=LOAD_TIMEOUT) as client:
            response = client.post(
                f"{root}/api/generate",
                json={
                    "model": model,
                    "prompt": "ok",
                    "stream": False,
                    "options": {"num_ctx": context},
                    "keep_alive": "30m",
                },
            )
    except httpx.RequestError as exc:
        raise RuntimeError_(f"не дозвониться до {root}: {exc}", retryable=True) from exc
    if response.status_code >= 400:
        raise RuntimeError_(
            f"среда выполнения отказала: {response.text[:200]}",
            retryable=response.status_code >= 500,
        )
    after = probe(settings)
    got = after.context_of(model)
    if got is None:
        raise RuntimeError_("среда выполнения не показывает модель загруженной")
    return Loaded(name=model, context=got)


def _models(response: httpx.Response) -> list[dict]:
    try:
        return response.json().get("models") or []
    except ValueError:
        return []
