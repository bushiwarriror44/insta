"""Try configured video backends in order until one returns a clip."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.config import Settings, get_settings
from app.generation.base import (
    GenerationError,
    GenerationRequest,
    GenerationResult,
    ProgressCallback,
    VideoBackend,
)
from app.services.generation_inputs import backend_supports_request


class ChainVideoBackend(VideoBackend):
    name = "auto"
    model_licence = "depends on the engine that succeeds"

    def __init__(
        self,
        settings: Settings | None = None,
        backends: list[VideoBackend] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._injected = backends

    def children(self) -> list[VideoBackend]:
        if self._injected is not None:
            return list(self._injected)
        from app.generation.registry import get_backend, parse_chain

        out: list[VideoBackend] = []
        for name in parse_chain(self.settings):
            if name == self.name:
                continue
            try:
                out.append(get_backend(name, self.settings))
            except NotImplementedError:
                continue
        return out

    def healthcheck(self) -> bool:
        return any(child.healthcheck() for child in self.children())

    def health_detail(self) -> str:
        parts = []
        for child in self.children():
            if child.healthcheck():
                parts.append(f"{child.name}: ok")
            else:
                parts.append(f"{child.name}: {child.health_detail() or 'нет'}")
        joined = "; ".join(parts) if parts else "цепочка пуста"
        if self.healthcheck():
            return joined
        return f"ни один рендер-бэкенд не настроен — {joined}"

    def estimate_cost(self, request: GenerationRequest) -> float:
        for child in self.children():
            if child.healthcheck() and backend_supports_request(child, request):
                return child.estimate_cost(request)
        return 0.0

    def generate(
        self,
        request: GenerationRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        errors: list[str] = []
        for child in self.children():
            if not child.healthcheck():
                errors.append(child.health_detail() or f"{child.name}: выключен")
                continue
            if not backend_supports_request(child, request):
                errors.append(f"{child.name}: не поддерживает режим {request.mode}")
                continue
            try:
                result = child.generate(request, out_dir, on_progress=on_progress)
            except GenerationError as exc:
                if not exc.retryable:
                    raise
                errors.append(f"{child.name}: {exc}")
                continue
            except httpx.RequestError as exc:
                errors.append(f"{child.name}: {exc}")
                continue
            return GenerationResult(
                video_path=result.video_path,
                generator=result.generator,
                cost_usd=result.cost_usd,
                seed=result.seed,
                backend=child.name,
            )
        if not errors:
            raise GenerationError(self.health_detail(), retryable=True)
        raise GenerationError("; ".join(errors), retryable=True)
