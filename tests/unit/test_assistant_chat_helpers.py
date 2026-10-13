from app.assistant.chat import (
    _generation_create_detail,
    _generation_step_from_create_result,
    _headers,
    _will_wait_render_later,
    build_assistant_thread,
)
from app.config import Settings


def test_headers_skips_non_ascii_agent_api_key():
    settings = Settings(agent_api_key="# если провайдер")
    assert "Authorization" not in _headers(settings)


def test_headers_strips_ascii_agent_api_key():
    settings = Settings(agent_api_key="  secret-key  ")
    assert _headers(settings)["Authorization"] == "Bearer secret-key"


def test_generation_create_detail_uses_backend_key():
    assert _generation_create_detail({"backend": "auto"}) == "backend=auto"
    assert _generation_create_detail({}) == ""


def test_generation_step_from_create_result():
    step = _generation_step_from_create_result({"id": 7, "backend": "fal"})
    assert step.kind == "generation"
    assert step.text == "queued"
    assert step.name == "7"
    assert step.detail == "backend=fal"


def test_will_wait_render_later():
    calls = [
        {"function": {"name": "create_render", "arguments": "{}"}},
        {
            "function": {
                "name": "wait_render",
                "arguments": '{"job_id": 12}',
            }
        },
    ]
    assert _will_wait_render_later(calls, 0, 12) is True
    assert _will_wait_render_later(calls, 0, 99) is False


def test_build_assistant_thread_attachment_hint():
    thread = build_assistant_thread(
        [
            {"role": "user", "content": "go"},
            {
                "role": "user",
                "content": "render",
                "attachments": [{"filename": "ref.png", "media_type": "image"}],
            },
        ]
    )
    assert thread[0]["role"] == "system"
    assert "ref.png" in thread[0]["content"]
    assert "image_to_video" in thread[0]["content"]
    assert "[вложение: ref.png" in thread[-1]["content"]
