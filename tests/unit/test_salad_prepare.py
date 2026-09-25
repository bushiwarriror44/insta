"""Chat-triggered Salad start and in-container warmup."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.config import settings
from app.services import salad_gpu
from app.services.salad_gpu import (
    GATEWAY_PORT,
    LAUNCH_STATUS,
    PHASE_MODEL,
    PHASE_PATCH,
    PHASE_PULL,
    PrepStatus,
    GroupState,
    SaladProblem,
    warmup_script,
)

HOST = "tabasco.example.salad.cloud"
ORIGIN = f"https://{HOST}"


def _titles(lines: list) -> list[str]:
    return [line.title if isinstance(line, PrepStatus) else str(line) for line in lines]


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "salad_api_key", "salad-secret", raising=True)
    monkeypatch.setattr(settings, "salad_organization", "tws3", raising=True)
    monkeypatch.setattr(settings, "salad_project", "default", raising=True)
    monkeypatch.setattr(settings, "salad_container_group", "insta-duplicate", raising=True)
    monkeypatch.setattr(settings, "agent_model", "qwen3:32b", raising=True)


def _group(status: str, *, command: tuple[str, ...] = ("gpu-warmup",), port: int = GATEWAY_PORT) -> GroupState:
    return GroupState(status=status, dns=HOST, port=port, command=command, running_count=1)


def test_safe_detail_hides_a_415_body():
    text = salad_gpu._safe_detail(415, {"message": "Unsupported Media Type"})
    assert text == "Salad отклонил формат запроса."
    assert "Unsupported" not in text


def test_warmup_script_marks_itself_and_names_the_model():
    script = warmup_script("qwen3:32b")
    assert "gpu-warmup" in script
    assert "qwen3:32b" in script
    assert "127.0.0.1:11434" in script


def test_prepare_starts_stopped_group_and_waits_until_the_model_is_loaded(app_env, monkeypatch):
    _enable(monkeypatch)
    running = _group("running")
    seen: list[str] = []

    def start_group(settings=None):
        seen.append("start")
        return running

    calls = {"n": 0}

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _group("stopped")
        return running

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "start_group", start_group)
    with respx.mock:
        respx.get(f"{ORIGIN}/").mock(return_value=httpx.Response(200, text="Ollama is running"))
        respx.get(f"{ORIGIN}/api/ps").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3:32b"}]})
        )
        lines = []
        gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
        try:
            while True:
                lines.append(next(gen))
        except StopIteration as stop:
            base = stop.value
    assert seen == ["start"]
    assert LAUNCH_STATUS in _titles(lines)
    assert any(isinstance(line, PrepStatus) and line.phase == 2 for line in lines)
    assert base == f"{ORIGIN}/v1"


def test_prepare_patches_command_once_when_the_marker_is_missing(app_env, monkeypatch):
    _enable(monkeypatch)
    bare = _group("running", command=(), port=8888)
    patched = _group("running")
    calls = {"n": 0}

    def sequence(settings=None):
        calls["n"] += 1
        return bare if calls["n"] == 1 else patched

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    with respx.mock:
        route = respx.patch(salad_gpu._group_url(settings)).mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get(f"{ORIGIN}/").mock(return_value=httpx.Response(200, text="Ollama is running"))
        respx.get(f"{ORIGIN}/api/ps").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3:32b"}]})
        )
        gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
        lines = []
        try:
            while True:
                lines.append(next(gen))
        except StopIteration:
            pass
    assert route.called
    sent = route.calls[0].request
    raw = sent.read().decode()
    assert sent.headers["content-type"].startswith("application/merge-patch+json")
    assert "gpu-warmup" in raw
    assert str(GATEWAY_PORT) in raw
    assert PHASE_PATCH in _titles(lines)
    assert "salad-secret" not in raw


def test_prepare_continues_when_the_patch_is_415(app_env, monkeypatch):
    _enable(monkeypatch)
    bare = _group("running", command=(), port=8888)
    monkeypatch.setattr(salad_gpu, "get_group", lambda settings=None: bare)
    with respx.mock:
        route = respx.patch(salad_gpu._group_url(settings)).mock(
            return_value=httpx.Response(
                415,
                json={"message": "Unsupported Media Type"},
            )
        )
        respx.get(f"{ORIGIN}/").mock(return_value=httpx.Response(200, text="Ollama is running"))
        respx.get(f"{ORIGIN}/api/ps").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3:32b"}]})
        )
        gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            base = stop.value
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["content-type"].startswith("application/merge-patch+json")
    assert base == f"{ORIGIN}/v1"


def test_prepare_does_not_patch_when_warmup_is_already_installed(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(salad_gpu, "get_group", lambda settings=None: _group("running"))
    with respx.mock:
        route = respx.patch(salad_gpu._group_url(settings)).mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get(f"{ORIGIN}/").mock(return_value=httpx.Response(200, text="Ollama is running"))
        respx.get(f"{ORIGIN}/api/ps").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3:32b"}]})
        )
        gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            assert stop.value == f"{ORIGIN}/v1"
    assert not route.called


def test_prepare_times_out_when_the_model_never_loads(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(salad_gpu, "get_group", lambda settings=None: _group("running"))
    clock = {"t": 0.0}

    def jump() -> float:
        clock["t"] += salad_gpu.START_WAIT_S + salad_gpu.WARM_WAIT_S + 1
        return clock["t"]

    with respx.mock:
        respx.get(f"{ORIGIN}/").mock(return_value=httpx.Response(200, text="Ollama is running"))
        respx.get(f"{ORIGIN}/api/ps").mock(return_value=httpx.Response(200, json={"models": []}))
        gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None, clock=jump)
        with pytest.raises(SaladProblem, match="не успела прогреться"):
            next(gen)


def test_prepare_reports_deploying_and_model_phases(app_env, monkeypatch):
    _enable(monkeypatch)
    calls = {"n": 0}

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return GroupState(status="stopped", dns=HOST, port=GATEWAY_PORT, command=("gpu-warmup",))
        if calls["n"] < 4:
            return GroupState(
                status="deploying",
                dns=HOST,
                port=GATEWAY_PORT,
                command=("gpu-warmup",),
                creating_count=1,
            )
        return GroupState(status="running", dns=HOST, port=GATEWAY_PORT, command=("gpu-warmup",), running_count=1)

    ps = {"n": 0}

    def ps_side_effect(request):
        ps["n"] += 1
        if ps["n"] < 2:
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json={"models": [{"name": "qwen3:32b"}]})

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "start_group", lambda settings=None: sequence())
    with respx.mock:
        respx.get(f"{ORIGIN}/").mock(return_value=httpx.Response(200, text="Ollama is running"))
        respx.get(f"{ORIGIN}/api/ps").mock(side_effect=ps_side_effect)
        lines = []
        gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
        try:
            while True:
                lines.append(next(gen))
        except StopIteration as stop:
            base = stop.value
    titles = _titles(lines)
    assert PHASE_PULL in titles
    assert PHASE_MODEL in titles
    assert all(isinstance(line, PrepStatus) for line in lines)
    assert any(line.milestone and line.title == PHASE_PULL for line in lines)
    assert any(0 < line.ratio < 1 for line in lines)
    assert base == f"{ORIGIN}/v1"
