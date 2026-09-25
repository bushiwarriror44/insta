"""A Salad gateway cut mid-stream is one retry, not a dead host."""
from __future__ import annotations

import json

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


class _CutAfterText(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"\xd1\x83\xd0\xb6\xd0\xb5"}}]}\n\n'
        raise httpx.RemoteProtocolError("incomplete chunked read")


class PartialThenCut(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CutAfterText())


def test_complete_keeps_printed_text_when_the_stream_cuts(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    said: list[str] = []
    with httpx.Client(transport=PartialThenCut()) as client:
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
    assert message["content"] == "уже"
    assert message["cut"] == "Ответ оборвался на шлюзе."
    assert said == ["уже"]
    assert "tool_calls" not in message


class ThinkThenAnswer(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"<think>сначала"}}]}\n\n'
            'data: {"choices":[{"delta":{"reasoning":" и ещё","content":"</think>потом"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body)


def test_complete_splits_reasoning_from_the_answer(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    said: list[str] = []
    kinds: list[str] = []
    with httpx.Client(transport=ThinkThenAnswer()) as client:
        gen = _complete(
            client,
            settings,
            [{"role": "user", "content": "hi"}],
            said,
            tools=[],
        )
        try:
            while True:
                kinds.append(next(gen).kind)
        except StopIteration as stop:
            message = stop.value
    assert message["thinking"] == "сначала и ещё"
    assert message["content"] == "потом"
    assert message["cut"] == ""
    assert said == ["потом"]
    assert kinds == ["think", "think", "token"]


class PlainCut(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise RuntimeError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        )


def test_complete_hides_a_non_httpx_stream_cut(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    with httpx.Client(transport=PlainCut()) as client:
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
            text = str(exc)
    assert "оборвал" in text
    assert "incomplete" not in text
    assert "peer closed" not in text


class MediaThenOk(httpx.BaseTransport):
    def __init__(self) -> None:
        self.n = 0
        self.second: httpx.Request | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.n += 1
        if self.n == 1:
            return httpx.Response(415, text="Unsupported Media Type")
        self.second = request
        body = 'data: {"choices":[{"delta":{"content":"ок"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body)


def test_complete_retries_415_without_extra_fields(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    transport = MediaThenOk()
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
    assert transport.second is not None
    sent = json.loads(transport.second.content.decode())
    assert "think" not in sent
    assert "options" not in sent
    assert "application/json" in transport.second.headers["content-type"]


class AlwaysMedia(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(415, text="Unsupported Media Type")


def test_complete_says_the_host_rejected_the_format(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    with httpx.Client(transport=AlwaysMedia()) as client:
        gen = _complete(
            client,
            settings,
            [{"role": "user", "content": "hi"}],
            [],
            tools=[],
        )
        try:
            next(gen)
            raise AssertionError("expected the format error")
        except AssistantError as exc:
            text = str(exc)
    assert "формат" in text
    assert "Unsupported" not in text


class BodyThenOk(httpx.BaseTransport):
    def __init__(self) -> None:
        self.n = 0
        self.second: httpx.Request | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.n += 1
        if self.n == 1:
            return httpx.Response(200, text="Unsupported Media Type")
        self.second = request
        body = 'data: {"choices":[{"delta":{"content":"ок"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body)


def test_complete_retries_when_the_body_is_the_media_phrase(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    transport = BodyThenOk()
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
    assert "Unsupported" not in message["content"]
    assert transport.second is not None
    sent = json.loads(transport.second.content.decode())
    assert "think" not in sent
    assert "options" not in sent


class AlwaysBody(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Unsupported Media Type")


def test_complete_hides_a_media_phrase_body(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    with httpx.Client(transport=AlwaysBody()) as client:
        gen = _complete(
            client,
            settings,
            [{"role": "user", "content": "hi"}],
            [],
            tools=[],
        )
        try:
            next(gen)
            raise AssertionError("expected the format error")
        except AssistantError as exc:
            text = str(exc)
    assert "формат" in text
    assert "Unsupported" not in text


class PlainDisconnect(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known")


def test_complete_hides_a_plain_disconnect(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    with httpx.Client(transport=PlainDisconnect()) as client:
        gen = _complete(
            client,
            settings,
            [{"role": "user", "content": "hi"}],
            [],
            tools=[],
        )
        try:
            next(gen)
            raise AssertionError("expected a connection error")
        except AssistantError as exc:
            text = str(exc)
    assert text == "не дозвониться до модели. Напишите ещё раз."
    assert "incomplete" not in text
    assert "peer closed" not in text
    assert "example" not in text


class CauseCut(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            raise RuntimeError("incomplete chunked read")
        except RuntimeError as inner:
            raise RuntimeError("connection failed") from inner


def test_complete_reads_the_stream_cut_from_the_cause(app_env, monkeypatch):
    monkeypatch.setattr(settings, "agent_base_url", "https://example/v1", raising=True)
    with httpx.Client(transport=CauseCut()) as client:
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
            text = str(exc)
    assert "оборвал" in text
    assert "incomplete" not in text
    assert "peer closed" not in text

