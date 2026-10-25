"""Ordered connection attempts with structured diagnostic lines.

Preferred method first; on failure the next method runs. Each try is logged
via ``DiagnosticCollector.attempt`` so the UI can show method / status / next.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.diagnostics.collector import DiagnosticCollector

# Stable method ids for logs and tests.
METHOD_REUSE = "reuse"
METHOD_PLAYWRIGHT = "playwright"
METHOD_MOBILE_API = "mobile_api"
METHOD_MINT_MOBILE = "mint_mobile"
METHOD_STUDIO_HEADLESS = "studio_headless"
METHOD_VNC = "vnc"


@dataclass
class ConnectionLadder:
    """Track which methods were tried and build a short finish summary."""

    collector: DiagnosticCollector
    tried: list[str] = field(default_factory=list)
    succeeded_method: str | None = None

    def start(self, method: str, detail: str = "", *, next_method: str | None = None) -> None:
        self.tried.append(method)
        self.collector.attempt(method, "started", detail, next_method=next_method)

    def ok(self, method: str, detail: str = "") -> None:
        self.succeeded_method = method
        self.collector.attempt(method, "ok", detail)

    def fail(
        self,
        method: str,
        detail: str = "",
        *,
        error: str | None = None,
        next_method: str | None = None,
    ) -> None:
        self.collector.attempt(
            method, "fail", detail, error=error, next_method=next_method
        )

    def skip(self, method: str, detail: str = "", *, next_method: str | None = None) -> None:
        self.collector.attempt(method, "skip", detail, next_method=next_method)

    def summary_ok(self) -> str:
        if not self.succeeded_method:
            return "Сессия создана"
        prior = [m for m in self.tried if m != self.succeeded_method]
        if not prior:
            return f"удалось на {self.succeeded_method}"
        return f"удалось на {self.succeeded_method} после {', '.join(prior)}"

    def summary_fail(self, last_error: str | None = None) -> str:
        methods = ", ".join(self.tried) if self.tried else "нет попыток"
        base = f"все методы исчерпаны ({methods})"
        if last_error:
            return f"{base}: {last_error}"
        return base
