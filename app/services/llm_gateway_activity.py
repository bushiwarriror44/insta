"""In-memory ring buffer of recent LLM gateway client hits."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

Channel = Literal["llm", "mcp"]

_MAX = 50
_lock = threading.Lock()


@dataclass(frozen=True)
class LlmGatewayActivityEvent:
    at: str
    channel: Channel
    method: str
    path: str
    client_ip: str
    user_agent: str
    status: int
    detail: str = ""


_events: deque[LlmGatewayActivityEvent] = deque(maxlen=_MAX)


def clear_activity() -> None:
    with _lock:
        _events.clear()


def record_activity(
    *,
    channel: Channel,
    method: str,
    path: str,
    client_ip: str,
    user_agent: str,
    status: int,
    detail: str = "",
) -> None:
    event = LlmGatewayActivityEvent(
        at=datetime.now(timezone.utc).isoformat(),
        channel=channel,
        method=(method or "GET").upper()[:16],
        path=(path or "/")[:200],
        client_ip=(client_ip or "")[:64],
        user_agent=(user_agent or "")[:120],
        status=int(status),
        detail=(detail or "").replace("\n", " ")[:160],
    )
    with _lock:
        _events.appendleft(event)


def list_activity() -> list[dict]:
    with _lock:
        return [asdict(item) for item in _events]
