"""Tests for app.config.Settings."""
from __future__ import annotations

from pathlib import Path

from app.config import Settings, settings


def test_singleton_settings_has_required_paths():
    assert isinstance(settings.data_dir, Path)
    assert isinstance(settings.sessions_dir, Path)
    assert isinstance(settings.devices_dir, Path)
    assert isinstance(settings.video_source_dir, Path)
    assert isinstance(settings.video_out_dir, Path)
    assert settings.sessions_dir.exists()
    assert settings.devices_dir.exists()


def test_salad_idle_stop_defaults_to_two_hours(monkeypatch):
    monkeypatch.delenv("SALAD_IDLE_STOP_MINUTES", raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.salad_idle_stop_minutes == 120


def test_settings_reads_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///custom.db")
    monkeypatch.setenv("DEFAULT_DAILY_POST_CAP", "7")
    monkeypatch.setenv("DEFAULT_MIN_GAP_HOURS", "5.5")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "alt"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "alt-s"))
    monkeypatch.setenv("DEVICES_DIR", str(tmp_path / "alt-d"))
    monkeypatch.setenv("PLAYWRIGHT_DIR", str(tmp_path / "alt-p"))
    monkeypatch.setenv("VIDEO_SOURCE_DIR", str(tmp_path / "alt-vs"))
    monkeypatch.setenv("VIDEO_OUT_DIR", str(tmp_path / "alt-vo"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "alt.log"))
    monkeypatch.setenv("PROXY_HEALTH_TIMEOUT_SEC", "20")
    monkeypatch.setenv("WAN_BASE_URL", "https://example.invalid/generate")
    monkeypatch.setenv("SALAD_API_KEY", "env-salad-key")
    monkeypatch.setenv("SALAD_ORGANIZATION", "acme")
    monkeypatch.setenv("SALAD_PROJECT", "gpu")
    monkeypatch.setenv("SALAD_CONTAINER_GROUP", "insta-gpu")
    monkeypatch.setenv("SALAD_IDLE_STOP_MINUTES", "15")

    fresh = Settings()
    assert fresh.database_url == "sqlite:///custom.db"
    assert fresh.default_daily_post_cap == 7
    assert fresh.default_min_gap_hours == 5.5
    assert fresh.log_level == "DEBUG"
    assert fresh.playwright_headless is False
    assert fresh.proxy_health_timeout_sec == 20
    assert fresh.sessions_dir == tmp_path / "alt-s"
    assert (tmp_path / "alt-s").is_dir()
    assert fresh.wan_base_url == "https://example.invalid/generate"
    assert fresh.salad_api_key == "env-salad-key"
    assert fresh.salad_organization == "acme"
    assert fresh.salad_project == "gpu"
    assert fresh.salad_container_group == "insta-gpu"
    assert fresh.salad_idle_stop_minutes == 15


def test_ensure_dir_creates_paths(tmp_path):
    target = tmp_path / "deep" / "nested"
    monkey_settings = Settings(
        data_dir=tmp_path / "data",
        sessions_dir=target,
        devices_dir=tmp_path / "dev",
        playwright_dir=tmp_path / "pw",
        video_source_dir=tmp_path / "src",
        video_out_dir=tmp_path / "out",
    )
    assert target.exists()
    assert monkey_settings.sessions_dir == target


def test_settings_validation_bounds(monkeypatch):
    import pytest as _pt
    from pydantic import ValidationError

    monkeypatch.setenv("DEFAULT_DAILY_POST_CAP", "999")
    with _pt.raises(ValidationError):
        Settings()
