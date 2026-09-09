"""Ollama autostart from the API lifespan."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import ollama_control
from app.services.runtime import Runtime


def test_ensure_started_is_a_no_op_when_disabled(app_env, monkeypatch):
    monkeypatch.setattr(ollama_control.settings, "ollama_autostart", False, raising=True)
    with patch("app.services.ollama_control.subprocess.Popen") as popen:
        status = ollama_control.ensure_started()
    assert status.reachable is False
    assert popen.call_count == 0


def test_ensure_started_skips_spawn_when_already_up(app_env, monkeypatch):
    monkeypatch.setattr(ollama_control.settings, "ollama_autostart", True, raising=True)
    monkeypatch.setattr(ollama_control.settings, "agent_model", "qwen3:8b", raising=True)
    with (
        patch(
            "app.services.ollama_control.probe",
            return_value=Runtime(reachable=True, base_url="http://localhost:11434", models=["qwen3:8b"]),
        ),
        patch("app.services.ollama_control.subprocess.Popen") as popen,
    ):
        status = ollama_control.ensure_started(pull=False)
    assert status.reachable is True
    assert status.model_ready is True
    assert popen.call_count == 0


def test_ensure_started_spawns_when_nothing_answers(app_env, monkeypatch):
    monkeypatch.setattr(ollama_control.settings, "ollama_autostart", True, raising=True)
    process = MagicMock()
    process.pid = 77
    with (
        patch(
            "app.services.ollama_control.probe",
            side_effect=[
                Runtime(reachable=False, base_url="http://localhost:11434"),
                Runtime(reachable=True, base_url="http://localhost:11434", models=[]),
            ],
        ),
        patch("app.services.ollama_control._binary", return_value="ollama"),
        patch("app.services.ollama_control.subprocess.Popen", return_value=process) as popen,
        patch("app.services.ollama_control._wait_until_up", return_value=True),
    ):
        status = ollama_control.ensure_started(pull=False)

    assert status.pid == 77
    assert popen.call_count == 1
    assert popen.call_args.args[0][:2] == ["ollama", "serve"]


def test_model_is_ready_matches_tag_and_family(app_env, monkeypatch):
    monkeypatch.setattr(ollama_control.settings, "agent_model", "qwen3:8b", raising=True)
    assert ollama_control._model_ready(["qwen3:8b"]) is True
    assert ollama_control._model_ready(["qwen3:latest"]) is True
    assert ollama_control._model_ready(["llama3:8b"]) is False
