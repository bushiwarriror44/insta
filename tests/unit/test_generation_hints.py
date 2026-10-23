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


def test_enrich_keeps_flash_attn_assertion_without_url_hint():
    # generate_server keeps only the tail of stderr — often without the word Traceback.
    raw = (
        "local: File \"/opt/wan/wan/modules/attention.py\", line 112, in flash_attention\n"
        "assert FLASH_ATTN_2_AVAILABLE\n"
        "AssertionError"
    )
    msg = enrich_generation_error(raw, backend="local")
    assert msg == raw
    assert "WAN_BASE_URL" not in msg
    assert LOCAL_RENDER_HINT_MARKER not in msg


def test_enrich_empty_message_returns_hint_only():
    msg = enrich_generation_error("", backend="auto")
    assert msg.startswith(LOCAL_RENDER_HINT_MARKER)


def test_enrich_524_names_the_salad_gateway_not_the_worker():
    msg = enrich_generation_error(
        "local: ошибка сервера 524 (generate)",
        backend="local",
    )
    assert "шлюз Salad" in msg
    assert "100" in msg
    assert "контейнера worker" not in msg
    assert "WAN_BASE_URL" not in msg


def test_enrich_wan_timeout_does_not_blame_the_url():
    msg = enrich_generation_error("local: wan timed out", backend="local")
    assert "30 минут" in msg
    assert "WAN_BASE_URL" not in msg
    assert "следующую попытку" in msg


def test_enrich_409_names_a_busy_gpu_not_the_worker():
    msg = enrich_generation_error(
        "local: generate завершился с кодом 409",
        backend="local",
    )
    assert "GPU уже рендерит" in msg
    assert "salad-gpu" in msg
    assert "контейнера worker" not in msg
    assert "WAN_BASE_URL" not in msg
