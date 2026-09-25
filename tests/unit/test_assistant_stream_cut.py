"""A Salad gateway cut mid-stream is one retry, not a dead host."""
from __future__ import annotations

import httpx

from app.assistant.chat import AssistantError, _complete
from app.config import settings


class CutThenOk(httpx.BaseTransport):
    def __init__(self) -> None:
        self.n = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.n += 1
        if self.n == 1:
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body (incomplete chunked read)"
            )
        body = 'data: {"choices":[{"delta":{"content":"сама"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body)


class AlwaysCut(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        )


def test_complete_retries_once_after_a_cut(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    transport = CutThenOk()
    said: list[str] = []
    with httpx.Client(transport=transport) as client:
        gen = _complete(
            client,
            settings,
            [{"role": "user", "content": "hi"}],
            said,
            tools=[],
        )
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            message = stop.value
    assert transport.n == 2
    assert message["content"] == "сама"
    assert said == ["сама"]


class BlipThenOk(httpx.BaseTransport):
    def __init__(self) -> None:
        self.n = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.n += 1
        if self.n == 1:
            return httpx.Response(520, text="origin")
        body = 'data: {"choices":[{"delta":{"content":"ок"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body)


def test_complete_retries_once_after_520(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    transport = BlipThenOk()
    with httpx.Client(transport=transport) as client:
        gen = _complete(
            client,
            settings,
            [{"role": "user", "content": "hi"}],
            [],
            tools=[],
        )
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            message = stop.value
    assert transport.n == 2
    assert message["content"] == "ок"


def test_complete_says_the_gateway_cut_the_reply(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    with httpx.Client(transport=AlwaysCut()) as client:
        gen = _complete(
            client,
            settings,
            [{"role": "user", "content": "hi"}],
            [],
            tools=[],
        )
        try:
            next(gen)
            raise AssertionError("expected the cut to surface")
        except AssistantError as exc:
            assert "оборвал" in str(exc)
            assert "incomplete" not in str(exc)
