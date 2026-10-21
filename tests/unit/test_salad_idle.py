"""Idle Stop for the Salad GPU group."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.models import GenerationJob, PipelineStatus
from app.services import salad_gpu, salad_idle
from app.services.gpu_slot import hold_for_video

START = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _enable(monkeypatch, minutes: int = 20) -> None:
    monkeypatch.setattr(settings, "salad_idle_stop_minutes", minutes, raising=True)
    monkeypatch.setattr(settings, "salad_api_key", "salad-secret", raising=True)
    monkeypatch.setattr(settings, "salad_organization", "tws3", raising=True)
    monkeypatch.setattr(settings, "salad_project", "default", raising=True)
    monkeypatch.setattr(settings, "salad_container_group", "insta-duplicate", raising=True)


def test_fresh_running_is_not_due(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.touch(settings, now=START - timedelta(hours=3))
    salad_idle.observe_status(settings, "running", now=START)
    assert salad_idle.idle_due(settings, status="running", busy=False, now=START) is False


def test_quiet_window_then_due(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.observe_status(settings, "running", now=START)
    salad_idle.touch(settings, now=START)
    assert salad_idle.idle_due(
        settings, status="running", busy=False, now=START + timedelta(minutes=19)
    ) is False
    assert salad_idle.idle_due(
        settings, status="running", busy=False, now=START + timedelta(minutes=20)
    ) is True


def test_recent_chat_postpones_stop(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.observe_status(settings, "running", now=START)
    salad_idle.touch(settings, now=START + timedelta(minutes=15))
    assert salad_idle.idle_due(
        settings, status="running", busy=False, now=START + timedelta(minutes=20)
    ) is False
    assert salad_idle.idle_due(
        settings, status="running", busy=False, now=START + timedelta(minutes=35)
    ) is True


def test_zero_minutes_disables(app_env, monkeypatch):
    _enable(monkeypatch, 0)
    salad_idle.observe_status(settings, "running", now=START)
    assert salad_idle.idle_due(
        settings, status="running", busy=False, now=START + timedelta(hours=5)
    ) is False


def test_video_lock_blocks_due_flag(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.observe_status(settings, "running", now=START)
    with hold_for_video(settings):
        assert salad_idle.idle_due(settings, status="running", busy=True, now=START + timedelta(hours=1)) is False


def test_tick_stops_quiet_group(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.observe_status(settings, "running", now=START)
    state = salad_gpu.GroupState(status="running", running_count=1)
    monkeypatch.setattr(salad_gpu, "get_group", lambda settings=None: state)
    called: list[str] = []
    monkeypatch.setattr(
        salad_gpu,
        "stop_group",
        lambda settings=None: called.append("stop") or state,
    )
    assert salad_idle.tick(settings, now=START + timedelta(minutes=20)) is True
    assert called == ["stop"]


def test_tick_skips_queued_local_render(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "wan_base_url", "", raising=True)
    salad_idle.observe_status(settings, "running", now=START)
    db = app_env.SessionLocal()
    db.add(GenerationJob(prompt="clip", backend="local", status=PipelineStatus.queued))
    db.commit()
    db.close()
    state = salad_gpu.GroupState(status="running", running_count=1)
    monkeypatch.setattr(salad_gpu, "get_group", lambda settings=None: state)
    monkeypatch.setattr(
        salad_gpu,
        "stop_group",
        lambda settings=None: (_ for _ in ()).throw(AssertionError("stop")),
    )
    assert salad_idle.tick(settings, now=START + timedelta(hours=2)) is False
    # Busy path advances last_used so idle is not due immediately after.
    assert salad_idle.idle_due(
        settings, status="running", busy=False, now=START + timedelta(hours=2)
    ) is False


def test_tick_skips_queued_auto_when_local_in_chain(app_env, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "wan_base_url", "", raising=True)
    monkeypatch.setattr(settings, "video_backend_chain", "local,fal", raising=True)
    salad_idle.observe_status(settings, "running", now=START)
    db = app_env.SessionLocal()
    db.add(GenerationJob(prompt="clip", backend="auto", status=PipelineStatus.queued))
    db.commit()
    db.close()
    state = salad_gpu.GroupState(status="running", running_count=1)
    monkeypatch.setattr(salad_gpu, "get_group", lambda settings=None: state)
    monkeypatch.setattr(
        salad_gpu,
        "stop_group",
        lambda settings=None: (_ for _ in ()).throw(AssertionError("stop")),
    )
    assert salad_idle.tick(settings, now=START + timedelta(hours=2)) is False


def test_presence_keeps_gpu_alive(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.observe_status(settings, "running", now=START)
    due_at = START + timedelta(hours=2)
    salad_idle.touch_presence("tab-aaaa-1111", settings, now=due_at - timedelta(seconds=30))
    state = salad_gpu.GroupState(status="running", running_count=1)
    monkeypatch.setattr(salad_gpu, "get_group", lambda settings=None: state)
    monkeypatch.setattr(
        salad_gpu,
        "stop_group",
        lambda settings=None: (_ for _ in ()).throw(AssertionError("stop")),
    )
    assert salad_idle.tick(settings, now=due_at) is False


def test_stale_presence_does_not_block(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.observe_status(settings, "running", now=START)
    salad_idle.touch_presence("tab-bbbb-2222", settings, now=START)
    assert salad_idle.presence_alive(settings, now=START + timedelta(seconds=30)) is True
    assert salad_idle.presence_alive(settings, now=START + timedelta(seconds=121)) is False


def test_two_viewers_prune_independently(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.touch_presence("viewer-one-aaa", settings, now=START)
    salad_idle.touch_presence(
        "viewer-two-bbb", settings, now=START + timedelta(seconds=90)
    )
    assert salad_idle.presence_alive(settings, now=START + timedelta(seconds=100)) is True
    # First viewer expired, second still within TTL.
    salad_idle.touch_presence(
        "viewer-two-bbb", settings, now=START + timedelta(seconds=100)
    )
    assert salad_idle.presence_alive(settings, now=START + timedelta(seconds=150)) is True
    assert salad_idle.presence_alive(settings, now=START + timedelta(seconds=250)) is False


def test_stopped_status_clears_running_since(app_env, monkeypatch):
    _enable(monkeypatch)
    salad_idle.observe_status(settings, "running", now=START)
    salad_idle.observe_status(settings, "stopped", now=START + timedelta(minutes=1))
    data = salad_idle._load(settings)
    assert "running_since" not in data
