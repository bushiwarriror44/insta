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
    platform: str = "instagram"
    login_identifier: Optional[str] = None
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
    login_surface: Optional[Literal["mobile", "desktop"]] = None
    session_file_exists: bool = False
    session_file_updated_at: Optional[datetime] = None
    session_source: Literal["database", "session_file", "playwright", "none"] = "none"
    posts_today: int = 0
    failures_today: int = 0
    notes: Optional[str] = None
    brief: Optional[str] = None
    hold_for_review: bool = False
    daily_spend_cap_usd: float = 0.0


class AccountIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    platform: Literal["instagram", "youtube", "tiktok"] = "instagram"
    password: str = Field(default="", max_length=500)
    proxy_label: str = Field(min_length=1)
    timezone: str = Field(default="UTC", max_length=64)
    daily_post_cap: int = Field(default=3, ge=1, le=20)
    min_gap_hours: float = Field(default=4.0, ge=0.5, le=24.0)
    active_hour_start: int = Field(default=10, ge=0, le=23)
    active_hour_end: int = Field(default=22, ge=1, le=23)
    caption_profile: Optional[str] = Field(default=None, max_length=32)
    totp_seed: Optional[str] = Field(default=None, max_length=120)
    session_id: Optional[str] = Field(default=None, max_length=1000)
    login_identifier: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=200)
    email_password: Optional[str] = Field(default=None, max_length=500)
    imap_host: Optional[str] = Field(default=None, max_length=200)
    backup_codes: Optional[str] = Field(default=None, max_length=4000)
    login_surface: Optional[Literal["mobile", "desktop"]] = None
    account_line: Optional[str] = Field(default=None, max_length=8000)
    vendor_line: Optional[str] = Field(default=None, max_length=8000)
    notes: Optional[str] = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def _validate_business_rules(self) -> "AccountIn":
        if (
            self.platform == "instagram"
            and not (self.password or "").strip()
            and not self.account_line
            and not (self.vendor_line or "").strip()
        ):
            raise ValueError("для Instagram нужен пароль")
        if self.active_hour_end <= self.active_hour_start:
            raise ValueError("active_hour_end должен быть больше active_hour_start")
        if self.caption_profile and self.caption_profile not in _CAPTION_PROFILE_ALLOWED:
            allowed = ", ".join(sorted(_CAPTION_PROFILE_ALLOWED))
            raise ValueError(f"caption_profile должен быть одним из: {allowed}")
        return self


class AccountProxyUpdate(BaseModel):
    proxy_label: str = Field(min_length=1)


class AccountNotesUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=8000)


class AccountTotpOut(BaseModel):
    totp_seed: str
    code: str
    seconds_remaining: int


class AccountSessionUpdate(BaseModel):
    session_id: str = Field(min_length=31, max_length=1000)


class AccountSessionOut(BaseModel):
    session_id: str
    source: Literal["database", "session_file"]
    session_file_exists: bool


class CookiesImportOut(BaseModel):
    format: Literal["dolphin", "playwright_state"]
    session_id: str
    session_id_imported: bool
    playwright_state_saved: bool
    session_file_cleared: bool


class DeviceFingerprintImportOut(BaseModel):
    username: str
    saved: bool


class ProxyHealthStepOut(BaseModel):
    ok: bool
    ip: Optional[str] = None
    geo_country: Optional[str] = None
    instagram_reachable: bool = False
    instagram_login_reachable: bool = False
    geo_mismatch: bool = False
    error: Optional[str] = None


class SessionStorageStepOut(BaseModel):
    has_session_id: bool
    session_file_exists: bool
    device_file_exists: bool
    session_source: Literal["database", "session_file", "playwright", "none"]


class InstagramAuthStepOut(BaseModel):
    ok: bool
    method: Literal["sessionid", "session_file", "playwright", "none"]
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
    kind: Literal["connection_test", "publish_job", "first_login", "mint_mobile_session"]
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
    browser_tab_hint: bool = False
    session_imported: bool = False
    connection_test: Optional[AccountConnectionTestOut] = None
    error: Optional[str] = None
    login_debug_available: bool = False
    logs: list[DiagnosticLogLineOut] = Field(default_factory=list)


class MintMobileSessionOut(BaseModel):
    run_id: int
    ok: bool
    challenge: bool = False
    session_id: Optional[str] = None
    error: Optional[str] = None
    logs: list[DiagnosticLogLineOut] = Field(default_factory=list)


class BrowserSessionOut(BaseModel):
    username: str
    status: Literal[
        "starting",
        "running",
        "awaiting_code",
        "saved",
        "error",
        "stopped",
    ]
    awaiting_code: bool = False
    vnc_path: Optional[str] = None
    page_url: Optional[str] = None
    error: Optional[str] = None
    login_surface: Optional[Literal["mobile", "desktop"]] = None
    warning: Optional[str] = None
    proxy_label: Optional[str] = None
    proxy_ip: Optional[str] = None
    proxy_geo_country: Optional[str] = None
    proxy_country: Optional[str] = None
    proxy_timezone: Optional[str] = None
    proxy_instagram_reachable: Optional[bool] = None
    proxy_instagram_login_reachable: Optional[bool] = None
    proxy_instagram_login_http_status: Optional[int] = None
    account_username: Optional[str] = None
    account_login: Optional[str] = None
    account_password: Optional[str] = None
    account_notes: Optional[str] = None
    logs: list[DiagnosticLogLineOut] = Field(default_factory=list)


class BrowserCodeIn(BaseModel):
    code: Optional[str] = Field(default=None, max_length=64)


class BrowserSaveOut(BrowserSessionOut):
    session_imported: bool = False
    session_id_saved: bool = False
    overall_ok: bool = False
    connection_test: Optional["AccountConnectionTestOut"] = None
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


class MediaArchiveIn(BaseModel):
    filenames: list[str] = Field(..., min_length=1, max_length=100)


# --- Jobs ------------------------------------------------------------------


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_username: Optional[str] = None
    source_video_path: str
    post_type: str = "reel"
    caption_template: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
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
    account_id: Optional[int] = None
    media_filename: Optional[str] = Field(default=None, min_length=1)
    video_filename: Optional[str] = Field(default=None, min_length=1)
    post_type: Literal["reel", "feed_photo", "feed_video", "youtube_short", "tiktok"] = "reel"
    caption_template: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    privacy: Optional[str] = None
    when: Optional[datetime] = None

    @model_validator(mode="after")
    def _require_media_filename(self) -> "EnqueueIn":
        if not (self.media_filename or self.video_filename):
            raise ValueError("нужно указать media_filename или video_filename")
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
    jobs_awaiting_review: int = 0
    jobs_failed_24h: int = 0
    open_questions: int = 0
    questions_account_id: Optional[int] = None
    risk_signals_24h: int
    quarantined_accounts: int
    daily_stats: list[DailyStatRow]
    recent_events: list[EventOut]


# --- Panel auth / operators ------------------------------------------------


class AuthMeOut(BaseModel):
    role: Optional[Literal["owner", "operator"]] = None
    label: Optional[str] = None


class PanelOperatorOut(BaseModel):
    id: int
    label: str
    created_at: datetime
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    active: bool


class PanelOperatorCreateIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class PanelOperatorCreatedOut(PanelOperatorOut):
    """Includes one-time plaintext password (only on create)."""

    password: str


# --- Panel gate / settings -------------------------------------------------


class PanelGateOut(BaseModel):
    allowed: bool
    entry_path: Optional[str] = None


class PanelSettingsOut(BaseModel):
    entry_path: str
    master_password_set: bool


class LlmGatewayActivityOut(BaseModel):
    at: str
    channel: Literal["llm", "mcp"]
    method: str
    path: str
    client_ip: str
    user_agent: str
    status: int


class LlmGatewayCredentialsOut(BaseModel):
    base_url: str
    api_key: str
    mcp_url: str
    mcp_json: str
    model: str
    upstream_ok: bool
    enabled: bool = True
    recent: list[LlmGatewayActivityOut] = Field(default_factory=list)


class LlmGatewayEnabledIn(BaseModel):
    enabled: bool


class PanelEntryPathUpdateIn(BaseModel):
    path: str = Field(min_length=12, max_length=200)
    current_password: str = Field(min_length=1)


class PanelMasterPasswordUpdateIn(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class WorkerProcessOut(BaseModel):
    running: bool
    ours: bool
    pid: Optional[int] = None
    seen_at: Optional[datetime] = None
    note: str = ""


class LogTailOut(BaseModel):
    name: str
    available: bool
    reason: str = ""
    lines: list[str] = Field(default_factory=list)


class GpuLogsOut(BaseModel):
    docker: list[LogTailOut]
    gpu: LogTailOut


class GpuOut(BaseModel):
    configured: bool
    status: Optional[str] = None
    billing: bool = False
    allocating_count: int = 0
    creating_count: int = 0
    running_count: int = 0
    stopping_count: int = 0
    chat_ok: bool = False
    wan_ok: Optional[bool] = None
    detail: str = ""
    idle_stop_minutes: int = 0
    deploy_started_at: Optional[datetime] = None
    connect_phase: Literal["idle", "pull", "boot", "gateway", "ready"] = "idle"
    connect_label: str = ""
    connect_detail: str = ""
    connect_ratio: float = 0.0


class AdminNotesOut(BaseModel):
    content: str
    updated_at: Optional[datetime] = None


class AdminNotesIn(BaseModel):
    content: str = Field(default="", max_length=200_000)
