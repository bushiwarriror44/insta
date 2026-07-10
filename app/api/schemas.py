"""Pydantic schemas for the admin HTTP API.

These mirror the SQLAlchemy ORM models in ``app.db.models`` but expose
fields the UI needs. Account passwords and session blobs stay server-side;
proxy URLs embed provider credentials — protect the admin API with
``ADMIN_TOKEN`` and trusted networks.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CAPTION_PROFILE_ALLOWED = {"nature", "lifestyle", "fitness", "food", "travel"}


class HealthOut(BaseModel):
    ok: bool
    version: str
    auth_required: bool


# --- Proxies ---------------------------------------------------------------


class ProxyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    url: str
    country: Optional[str] = None
    timezone: Optional[str] = None
    is_healthy: bool
    last_known_ip: Optional[str] = None
    last_geo_country: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    notes: Optional[str] = None
    accounts_count: int = 0
    instagram_reachable: Optional[bool] = None
    geo_mismatch_warning: bool = False


class ProxyIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    country: Optional[str] = Field(default=None, max_length=8)
    timezone: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = None
    skip_health_check: bool = False


class ProxyUpdate(BaseModel):
    """Full replacement of mutable proxy fields (label is the URL path segment)."""

    url: str = Field(min_length=1, max_length=500)
    country: Optional[str] = Field(default=None, max_length=8)
    timezone: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = None
    skip_health_check: bool = False


# --- Accounts --------------------------------------------------------------


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    status: str
    proxy_id: Optional[int] = None
    proxy_label: Optional[str] = None
    proxy_country: Optional[str] = None
    proxy_geo_country: Optional[str] = None
    proxy_is_healthy: Optional[bool] = None
    proxy_last_ip: Optional[str] = None
    timezone: str
    daily_post_cap: int
    min_gap_hours: float
    active_hour_start: int
    active_hour_end: int
    last_publish_at: Optional[datetime] = None
    last_idle_warmup_at: Optional[datetime] = None
    last_session_rotation_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    caption_profile: Optional[str] = None
    has_totp: bool = False
    has_session_id: bool = False
    session_file_exists: bool = False
    session_file_updated_at: Optional[datetime] = None
    session_source: Literal["database", "session_file", "none"] = "none"
    posts_today: int = 0
    failures_today: int = 0


class AccountIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=500)
    proxy_label: str = Field(min_length=1)
    timezone: str = Field(default="UTC", max_length=64)
    daily_post_cap: int = Field(default=3, ge=1, le=20)
    min_gap_hours: float = Field(default=4.0, ge=0.5, le=24.0)
    active_hour_start: int = Field(default=10, ge=0, le=23)
    active_hour_end: int = Field(default=22, ge=1, le=23)
    caption_profile: Optional[str] = Field(default=None, max_length=32)
    totp_seed: Optional[str] = Field(default=None, max_length=120)
    session_id: Optional[str] = Field(default=None, max_length=1000)
    email: Optional[str] = Field(default=None, max_length=200)
    email_password: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_business_rules(self) -> "AccountIn":
        if self.active_hour_end <= self.active_hour_start:
            raise ValueError("active_hour_end must be greater than active_hour_start")
        if self.caption_profile and self.caption_profile not in _CAPTION_PROFILE_ALLOWED:
            allowed = ", ".join(sorted(_CAPTION_PROFILE_ALLOWED))
            raise ValueError(f"caption_profile must be one of: {allowed}")
        return self


class AccountProxyUpdate(BaseModel):
    proxy_label: str = Field(min_length=1)


class AccountSessionUpdate(BaseModel):
    session_id: str = Field(min_length=31, max_length=1000)


class AccountSessionOut(BaseModel):
    session_id: str
    source: Literal["database", "session_file"]
    session_file_exists: bool


class ProxyHealthStepOut(BaseModel):
    ok: bool
    ip: Optional[str] = None
    geo_country: Optional[str] = None
    instagram_reachable: bool = False
    geo_mismatch: bool = False
    error: Optional[str] = None


class SessionStorageStepOut(BaseModel):
    has_session_id: bool
    session_file_exists: bool
    device_file_exists: bool
    session_source: Literal["database", "session_file", "none"]


class InstagramAuthStepOut(BaseModel):
    ok: bool
    method: Literal["sessionid", "session_file", "none"]
    ig_username: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[
        Literal["session_missing", "session_expired", "challenge_required"]
    ] = None
    challenge: bool = False


class DiagnosticLogLineOut(BaseModel):
    ts: str
    level: Literal["info", "warn", "error"]
    step: str
    message: str


class DiagnosticRunOut(BaseModel):
    id: int
    kind: Literal["connection_test", "publish_job", "first_login"]
    account_id: int
    account_username: Optional[str] = None
    job_id: Optional[int] = None
    status: Literal["running", "ok", "warn", "fail"]
    summary: Optional[str] = None
    logs: list[DiagnosticLogLineOut] = Field(default_factory=list)
    created_at: datetime
    finished_at: Optional[datetime] = None


class AccountConnectionTestOut(BaseModel):
    username: str
    proxy_assigned: bool
    proxy_label: Optional[str] = None
    proxy_health: ProxyHealthStepOut
    session_storage: SessionStorageStepOut
    instagram_auth: InstagramAuthStepOut
    overall_ok: bool
    checked_at: datetime
    run_id: int
    logs: list[DiagnosticLogLineOut] = Field(default_factory=list)


class FirstLoginOut(BaseModel):
    run_id: int
    ok: bool
    challenge: bool = False
    session_imported: bool = False
    connection_test: Optional[AccountConnectionTestOut] = None
    error: Optional[str] = None
    logs: list[DiagnosticLogLineOut] = Field(default_factory=list)


# --- Media -----------------------------------------------------------------


class VideoOut(BaseModel):
    filename: str
    size_bytes: int
    modified_at: datetime
    media_type: Literal["image", "video"]
    duration_sec: Optional[float] = None


class UploadOut(BaseModel):
    filename: str
    size_bytes: int
    media_type: Literal["image", "video"]
    duration_sec: Optional[float] = None


# --- Jobs ------------------------------------------------------------------


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_username: Optional[str] = None
    source_video_path: str
    post_type: str = "reel"
    caption_template: Optional[str] = None
    scheduled_for: datetime
    status: str
    attempts: int
    last_error: Optional[str] = None
    next_attempt_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class EnqueueIn(BaseModel):
    username: str = Field(min_length=1)
    media_filename: Optional[str] = Field(default=None, min_length=1)
    video_filename: Optional[str] = Field(default=None, min_length=1)
    post_type: Literal["reel", "feed_photo", "feed_video"] = "reel"
    caption_template: Optional[str] = None
    when: Optional[datetime] = None

    @model_validator(mode="after")
    def _require_media_filename(self) -> "EnqueueIn":
        if not (self.media_filename or self.video_filename):
            raise ValueError("media_filename is required")
        return self

    @property
    def selected_filename(self) -> str:
        return self.media_filename or self.video_filename or ""


# --- Publications ----------------------------------------------------------


class PublicationOut(BaseModel):
    id: int
    job_id: int
    account_id: int
    account_username: Optional[str] = None
    post_type: Optional[str] = None
    media_id: Optional[str] = None
    media_code: Optional[str] = None
    final_media_path: Optional[str] = None
    final_caption: Optional[str] = None
    success: bool
    error: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    play_count: Optional[int] = None
    save_count: Optional[int] = None
    share_count: Optional[int] = None
    last_stats_at: Optional[datetime] = None
    created_at: datetime


# --- Events ----------------------------------------------------------------


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: Optional[int] = None
    account_username: Optional[str] = None
    level: str
    kind: str
    message: str
    created_at: datetime


# --- Dashboard -------------------------------------------------------------


class DailyStatRow(BaseModel):
    username: str
    posts_count: int
    failures_count: int


class DashboardSummary(BaseModel):
    accounts_total: int
    accounts_active: int
    accounts_blocked: int
    proxies_healthy: int
    proxies_total: int
    jobs_queued: int
    jobs_running: int
    jobs_done_today: int
    jobs_dead_total: int
    risk_signals_24h: int
    quarantined_accounts: int
    daily_stats: list[DailyStatRow]
    recent_events: list[EventOut]
