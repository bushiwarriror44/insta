"""Chat-triggered Salad start and in-container warmup."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import settings
from app.services import salad_gpu
from app.services.salad_gpu import (
    GATEWAY_PORT,
    WAN_GATEWAY_PORT,
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
_READY = ("gpu-warmup", "gateway-ipv6", "wan-dashscope")


def _titles(lines: list) -> list[str]:
    return [line.title if isinstance(line, PrepStatus) else str(line) for line in lines]


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "salad_api_key", "salad-secret", raising=True)
    monkeypatch.setattr(settings, "salad_organization", "tws3", raising=True)
    monkeypatch.setattr(settings, "salad_project", "default", raising=True)
    monkeypatch.setattr(settings, "salad_container_group", "insta-duplicate", raising=True)
    monkeypatch.setattr(settings, "agent_model", "qwen3:32b", raising=True)
    monkeypatch.setattr(settings, "wan_base_url", "", raising=True)


def _group(status: str, *, command: tuple[str, ...] = _READY, port: int = GATEWAY_PORT) -> GroupState:
    return GroupState(status=status, dns=HOST, port=port, command=command, running_count=1)


def test_safe_detail_hides_a_415_body():
    text = salad_gpu._safe_detail(415, {"message": "Unsupported Media Type"})
    assert text == "Salad отклонил формат запроса."
    assert "Unsupported" not in text


def test_warmup_script_marks_itself_and_names_the_model():
    script = warmup_script("qwen3:32b")
    assert "gpu-warmup" in script
    assert "gateway-ipv6" in script
    assert "wan-dashscope" in script
    assert "pip install -q dashscope" in script
    assert "[::]:8080" in script
    assert "qwen3:32b" in script
    assert "127.0.0.1:11434" in script


def test_prepare_starts_stopped_group_and_waits_until_the_model_is_loaded(app_env, monkeypatch):
    _enable(monkeypatch)
    running = _group("running")
    seen: list[str] = []

    def request_start(settings=None):
        seen.append("start")

    calls = {"n": 0}

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _group("stopped")
        return running

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "request_start", request_start)
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


def test_prepare_patches_wan_gateway_port_when_wan_base_url_is_set(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "wan_base_url", "https://gpu.example/generate", raising=True)
    bare = _group("running", command=(), port=8888)
    patched = _group("running", port=WAN_GATEWAY_PORT)
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
        try:
            while True:
                next(gen)
        except StopIteration:
            pass
    assert route.called
    body = route.calls[0].request.read().decode()
    payload = json.loads(body)
    assert payload["networking"]["port"] == WAN_GATEWAY_PORT
    assert payload["networking"]["port"] != GATEWAY_PORT


def test_prepare_skips_patch_when_port_is_unknown_and_warmup_is_installed(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "wan_base_url", "https://gpu.example/generate", raising=True)
    monkeypatch.setattr(
        salad_gpu,
        "get_group",
        lambda settings=None: _group("running", port=0),
    )
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


def test_prepare_patches_command_without_port_when_port_is_unknown(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "wan_base_url", "https://gpu.example/generate", raising=True)
    bare = _group("running", command=(), port=0)
    patched = _group("running", port=0)
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
        try:
            while True:
                next(gen)
        except StopIteration:
            pass
    assert route.called
    payload = json.loads(route.calls[0].request.read().decode())
    assert "networking" not in payload
    assert "gateway-ipv6" in payload["container"]["command"][2]


def test_prepare_skips_patch_when_wan_port_and_warmup_are_already_set(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "wan_base_url", "https://gpu.example/generate", raising=True)
    monkeypatch.setattr(
        salad_gpu,
        "get_group",
        lambda settings=None: _group("running", port=WAN_GATEWAY_PORT),
    )
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
            return GroupState(status="stopped", dns=HOST, port=GATEWAY_PORT, command=_READY)
        if calls["n"] < 4:
            return GroupState(
                status="deploying",
                dns=HOST,
                port=GATEWAY_PORT,
                command=_READY,
                creating_count=1,
            )
        return GroupState(status="running", dns=HOST, port=GATEWAY_PORT, command=_READY, running_count=1)

    ps = {"n": 0}

    def ps_side_effect(request):
        ps["n"] += 1
        if ps["n"] < 2:
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json={"models": [{"name": "qwen3:32b"}]})

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "request_start", lambda settings=None: None)
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


def test_prepare_waits_through_a_long_image_pull(app_env, monkeypatch):
    _enable(monkeypatch)
    clock = {"t": 0.0}
    calls = {"n": 0}

    def tick() -> float:
        return clock["t"]

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return GroupState(status="stopped", dns=HOST, port=GATEWAY_PORT, command=_READY)
        if clock["t"] < salad_gpu.PULL_WAIT_S - 60:
            return GroupState(
                status="deploying",
                dns=HOST,
                port=GATEWAY_PORT,
                command=_READY,
                creating_count=1,
            )
        return GroupState(status="running", dns=HOST, port=GATEWAY_PORT, command=_READY, running_count=1)

    def pause(_s: float) -> None:
        clock["t"] += 10 * 60

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "request_start", lambda settings=None: None)
    with respx.mock:
        respx.get(f"{ORIGIN}/").mock(return_value=httpx.Response(200, text="Ollama is running"))
        respx.get(f"{ORIGIN}/api/ps").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3:32b"}]})
        )
        gen = salad_gpu.prepare_for_chat(settings, pause=pause, clock=tick)
        lines = []
        try:
            while True:
                lines.append(next(gen))
        except StopIteration as stop:
            base = stop.value
    assert PHASE_PULL in _titles(lines)
    assert clock["t"] > salad_gpu.START_WAIT_S
    assert base == f"{ORIGIN}/v1"


def test_prepare_says_image_still_pulling_after_pull_budget(app_env, monkeypatch):
    _enable(monkeypatch)
    clock = {"t": 0.0}

    def jump() -> float:
        clock["t"] += salad_gpu.PULL_WAIT_S + 1
        return clock["t"]

    monkeypatch.setattr(
        salad_gpu,
        "get_group",
        lambda settings=None: GroupState(
            status="deploying",
            dns=HOST,
            port=GATEWAY_PORT,
            command=_READY,
            creating_count=1,
        ),
    )
    gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None, clock=jump)
    with pytest.raises(SaladProblem, match="всё ещё качается"):
        next(gen)


def test_prepare_keeps_waiting_when_pull_polls_drop(app_env, monkeypatch):
    _enable(monkeypatch)
    calls = {"n": 0}
    deploying = GroupState(
        status="deploying",
        dns=HOST,
        port=GATEWAY_PORT,
        command=_READY,
        creating_count=1,
    )

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return deploying
        if calls["n"] <= 7:
            raise SaladProblem(salad_gpu.SALAD_UNREACHABLE)
        return _group("running")

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
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
    details = " ".join(line.detail for line in lines if isinstance(line, PrepStatus))
    assert "напишите снова" not in details
    assert "нет связи с Salad" in details
    assert PHASE_PULL in _titles(lines)
    assert calls["n"] == 8
    assert base == f"{ORIGIN}/v1"


def test_prepare_retries_salad_api_while_the_image_downloads(app_env, monkeypatch):
    _enable(monkeypatch)
    calls = {"n": 0}

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise SaladProblem(salad_gpu.SALAD_UNREACHABLE)
        if calls["n"] < 5:
            return GroupState(
                status="deploying",
                dns=HOST,
                port=GATEWAY_PORT,
                command=_READY,
                creating_count=1,
            )
        return _group("running")

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
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
    titles = _titles(lines)
    assert salad_gpu.PHASE_API in titles
    assert PHASE_PULL in titles
    assert salad_gpu.API_DOWN_WHILE_PULL not in titles
    assert base == f"{ORIGIN}/v1"


def test_prepare_defers_gateway_patch_until_the_node_is_running(app_env, monkeypatch):
    _enable(monkeypatch)
    calls = {"n": 0}
    seen: list[str] = []

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] < 4:
            return GroupState(
                status="deploying",
                dns=HOST,
                port=GATEWAY_PORT,
                command=(),
                creating_count=1,
            )
        return GroupState(status="running", dns=HOST, port=GATEWAY_PORT, command=(), running_count=1)

    def tracking_patch(settings, state):
        seen.append(state.status)
        return _group("running")

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "patch_gateway", tracking_patch)
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
    assert seen == ["running"]
    titles = _titles(lines)
    assert titles.index(PHASE_PULL) < titles.index(PHASE_PATCH)
    assert base == f"{ORIGIN}/v1"


def test_prepare_says_api_is_down_before_any_status(app_env, monkeypatch):
    _enable(monkeypatch)

    def down(settings=None):
        raise SaladProblem(salad_gpu.SALAD_UNREACHABLE)

    monkeypatch.setattr(salad_gpu, "get_group", down)
    gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
    with pytest.raises(SaladProblem, match="API Salad не отвечает"):
        while True:
            next(gen)


def test_prepare_does_not_claim_a_pull_when_start_never_leaves(app_env, monkeypatch):
    _enable(monkeypatch)
    gets = {"n": 0}
    posts = {"n": 0}

    def sequence(settings=None):
        gets["n"] += 1
        return _group("stopped")

    def boom(settings=None):
        posts["n"] += 1
        raise SaladProblem(salad_gpu.SALAD_UNREACHABLE)

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "request_start", boom)
    lines = []
    gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
    with pytest.raises(SaladProblem, match="осталась остановленной"):
        while True:
            lines.append(next(gen))
    titles = _titles(lines)
    assert salad_gpu.SEND_START in titles
    assert LAUNCH_STATUS not in titles
    assert "качать образ" not in " ".join(titles)
    assert posts["n"] == salad_gpu.ACTION_API_ATTEMPTS
    assert gets["n"] == 1


def test_prepare_says_start_failed_when_salad_marks_failed(app_env, monkeypatch):
    _enable(monkeypatch)
    calls = {"n": 0}

    def sequence(settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return GroupState(status="stopped", dns=HOST, port=GATEWAY_PORT, command=_READY)
        return GroupState(status="failed", dns=HOST, port=GATEWAY_PORT, command=_READY)

    monkeypatch.setattr(salad_gpu, "get_group", sequence)
    monkeypatch.setattr(salad_gpu, "request_start", lambda settings=None: None)
    gen = salad_gpu.prepare_for_chat(settings, pause=lambda _s: None)
    with pytest.raises(SaladProblem, match="не удался"):
        while True:
            next(gen)
