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
    browser_auto_open_instagram: bool = Field(default=True)
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
    upload_max_mb: int = Field(default=512, ge=1, le=2048)
    image_compress_max_edge: int = Field(default=1920, ge=256, le=8192)
    image_compress_quality: int = Field(default=85, ge=1, le=95)

    reference_dir: Path = Field(default=Path("data/reference"))
    reference_allowed_hosts: str = Field(default="")
    reference_max_bytes: int = Field(default=256 * 1024)
    reference_timeout_seconds: float = Field(default=15.0)

    agent_backend: str = Field(default="openai-compat")
    agent_model: str = Field(default="qwen3:8b")
    agent_base_url: str = Field(default="http://localhost:11434/v1")
    agent_timeout_seconds: float = Field(default=600.0)
    assistant_timeout_seconds: float = Field(default=180.0)
    agent_api_key: str = Field(default="")
    worker_autostart: bool = Field(default=True)
    ollama_autostart: bool = Field(default=True)
    panel_base_url: str = Field(default="http://127.0.0.1:5173")
    screenshots_dir: Path = Field(default=Path("data/screenshots"))
    backup_dir: Path = Field(default=Path("data/backups"))
    backup_keep: int = Field(default=14, ge=1, le=90)
    media_url_secret: str = Field(default="")
    media_link_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    fal_api_key: str = Field(default="")
    fal_model: str = Field(default="fal-ai/wan-25-preview/text-to-video")
    video_backend: str = Field(default="auto")
    video_backend_chain: str = Field(
        default="fal,huggingface,pollinations,local,hfspace"
    )
    hf_token: str = Field(default="")
    hf_video_model: str = Field(default="Wan-AI/Wan2.1-T2V-1.3B")
    hf_inference_url: str = Field(default="https://router.huggingface.co")
    pollinations_video_url: str = Field(default="https://gen.pollinations.ai/video")
    pollinations_api_key: str = Field(default="")
    wan_base_url: str = Field(default="")
    wan_api_key: str = Field(default="")
    salad_api_key: str = Field(default="")
    salad_organization: str = Field(default="")
    salad_project: str = Field(default="")
    salad_container_group: str = Field(default="")
    hf_space_id: str = Field(default="")
    hf_space_api_name: str = Field(default="predict")
    generation_poll_seconds: float = Field(default=5.0)
    generation_timeout_seconds: float = Field(default=900.0)
    daily_spend_cap_usd: float = Field(default=0.0, ge=0)
    outbound_proxy: str = Field(default="")
    media_dir: Path = Field(default=Path("data/videos/source"))

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
        "reference_dir",
        "media_dir",
        "screenshots_dir",
        "backup_dir",
    )
    @classmethod
    def _ensure_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v


settings = Settings()


def get_settings() -> Settings:
    return settings
