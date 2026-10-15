from app.generation.hints import (
    LOCAL_RENDER_HINT_MARKER,
    enrich_generation_error,
)


def test_enrich_appends_switch_hint_for_cloud_backend():
    msg = enrich_generation_error("pollinations rejected", backend="fal")
    assert LOCAL_RENDER_HINT_MARKER in msg
    assert "pollinations rejected" in msg
    assert "WAN_BASE_URL" in msg


def test_enrich_appends_check_hint_for_local_backend():
    msg = enrich_generation_error("connection refused", backend="local")
    assert LOCAL_RENDER_HINT_MARKER in msg
    assert "connection refused" in msg
    assert "проверьте" in msg.lower()


def test_enrich_does_not_duplicate_marker():
    once = enrich_generation_error("err", backend="fal")
    twice = enrich_generation_error(once, backend="fal")
    assert twice == once
    assert once.count(LOCAL_RENDER_HINT_MARKER) == 1


def test_enrich_keeps_wan_traceback_without_url_hint():
    raw = "ModuleNotFoundError: No module named 'dashscope'"
    msg = enrich_generation_error(raw, backend="local")
    assert msg == raw
    assert LOCAL_RENDER_HINT_MARKER not in msg


def test_enrich_empty_message_returns_hint_only():
    msg = enrich_generation_error("", backend="auto")
    assert msg.startswith(LOCAL_RENDER_HINT_MARKER)
