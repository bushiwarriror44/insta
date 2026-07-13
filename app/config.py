"""Centralized application settings.

Uses pydantic-settings to load values from environment variables and the
optional ``.env`` file. All other modules must import the singleton
``settings`` from here instead of reading os.environ directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(default="sqlite:///data/app.db")

    data_dir: Path = Field(default=Path("data"))
    sessions_dir: Path = Field(default=Path("data/sessions"))
    devices_dir: Path = Field(default=Path("data/devices"))
    playwright_dir: Path = Field(default=Path("data/playwright"))
    video_source_dir: Path = Field(default=Path("data/videos/source"))
    video_out_dir: Path = Field(default=Path("data/videos/out"))

    log_level: str = Field(default="INFO")
    log_file: Optional[Path] = Field(default=Path("data/app.log"))

    telegram_bot_token: Optional[str] = Field(default=None)
    telegram_chat_id: Optional[str] = Field(default=None)

    default_daily_post_cap: int = Field(default=3, ge=1, le=20)
    default_min_gap_hours: float = Field(default=4.0, ge=0.5, le=24.0)
    default_active_hour_start: int = Field(default=10, ge=0, le=23)
    default_active_hour_end: int = Field(default=23, ge=1, le=23)

    proxy_health_url: str = Field(default="https://api.ipify.org?format=json")
    proxy_health_timeout_sec: int = Field(default=15, ge=3, le=60)

    playwright_headless: bool = Field(default=True)

    browser_vnc_enabled: bool = Field(default=False)
    browser_session_timeout_min: int = Field(default=30, ge=5, le=180)
    browser_display_base: int = Field(default=100, ge=10, le=200)
    browser_lightweight: bool = Field(default=True)
    browser_goto_timeout_sec: int = Field(default=25, ge=10, le=90)
    browser_auto_open_instagram: bool = Field(default=False)
    browser_autofill_on_start: bool = Field(default=False)

    scheduler_tz: str = Field(default="UTC")
    worker_poll_interval_sec: int = Field(default=20, ge=5)
    job_max_attempts: int = Field(default=4, ge=1, le=10)

    admin_token: Optional[str] = Field(default=None)
    cors_allowed_origins_raw: str = Field(
        default="http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
        alias="CORS_ALLOWED_ORIGINS",
    )
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1, le=65535)
    upload_max_mb: int = Field(default=200, ge=1, le=2048)

    @property
    def cors_allowed_origins(self) -> list[str]:
        raw = (self.cors_allowed_origins_raw or "").strip()
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]

    @field_validator(
        "data_dir",
        "sessions_dir",
        "devices_dir",
        "playwright_dir",
        "video_source_dir",
        "video_out_dir",
    )
    @classmethod
    def _ensure_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v


settings = Settings()
