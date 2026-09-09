"""Lookup for the configured content-agent backend."""

from __future__ import annotations

from app.agent.openai_compat import OpenAICompatAgent
from app.agent.planner import AgentBackend
from app.config import Settings, get_settings

#: One entry, and the lookup stays because the backend is a setting the
#: operator can point at something else — LM Studio, a vLLM box on the
#: network — without that being a code change.
_BACKENDS: dict[str, type[AgentBackend]] = {
    OpenAICompatAgent.name: OpenAICompatAgent,
}


def get_agent(
    name: str | None = None, settings: Settings | None = None
) -> AgentBackend:
    settings = settings or get_settings()
    name = name or settings.agent_backend
    try:
        backend = _BACKENDS[name]
    except KeyError:
        raise NotImplementedError(f"no content agent named {name!r}") from None
    return backend(settings)


def available_agents() -> list[str]:
    return sorted(_BACKENDS)
