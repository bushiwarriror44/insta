"""SQLAlchemy ORM models for the publisher service."""
from __future__ import annotations

import enum
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AccountStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    challenge = "challenge"
    blocked = "blocked"
    cooldown = "cooldown"


class PostJobStatus(str, enum.Enum):
    awaiting_review = "awaiting_review"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    dead = "dead"
    cancelled = "cancelled"


class Platform(str, enum.Enum):
    instagram = "instagram"
    youtube = "youtube"
    tiktok = "tiktok"


class PostType(str, enum.Enum):
    reel = "reel"
    feed_photo = "feed_photo"
    feed_video = "feed_video"
    youtube_short = "youtube_short"
    tiktok = "tiktok"


class PipelineStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    dead = "dead"
    cancelled = "cancelled"


class AssetSource(str, enum.Enum):
    upload = "upload"
    generated = "generated"
    composed = "composed"


class AssetKind(str, enum.Enum):
    video = "video"
    audio = "audio"


class SourceKind(str, enum.Enum):
    url = "url"
    file = "file"


class RunTrigger(str, enum.Enum):
    job = "job"
    preview = "preview"


class EventLevel(str, enum.Enum):
    info = "info"
    warn = "warn"
    error = "error"
    critical = "critical"


class DiagnosticRunKind(str, enum.Enum):
    connection_test = "connection_test"
    publish_job = "publish_job"
    first_login = "first_login"
    mint_mobile_session = "mint_mobile_session"
    browser_session = "browser_session"
    studio_login = "studio_login"


class DiagnosticRunStatus(str, enum.Enum):
    running = "running"
    ok = "ok"
    warn = "warn"
    fail = "fail"


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(120), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_known_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_geo_country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list["Account"]] = relationship(back_populates="proxy")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), unique=True)
    settings_json: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str] = mapped_column(String(500))
    locale: Mapped[str] = mapped_column(String(16))
    country: Mapped[str] = mapped_column(String(8))
    country_code: Mapped[int] = mapped_column(Integer)
    timezone_offset: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped["Account"] = relationship(back_populates="device")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("platform", "username", name="uq_account_platform_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, native_enum=False), default=Platform.instagram, index=True
    )
    username: Mapped[str] = mapped_column(String(120), index=True)
    password: Mapped[str] = mapped_column(String(500), default="")
    login_identifier: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email_password: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    imap_host: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    totp_seed: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    backup_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    login_surface: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, native_enum=False), default=AccountStatus.active, index=True
    )
    proxy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("proxies.id"), nullable=True)
    proxy: Mapped[Optional[Proxy]] = relationship(back_populates="accounts")
    device: Mapped[Optional[Device]] = relationship(
        back_populates="account", uselist=False, cascade="all, delete-orphan"
    )

    daily_post_cap: Mapped[int] = mapped_column(Integer, default=3)
    min_gap_hours: Mapped[float] = mapped_column(Float, default=4.0)
    active_hour_start: Mapped[int] = mapped_column(Integer, default=10)
    active_hour_end: Mapped[int] = mapped_column(Integer, default=23)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")

    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_warmup_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_publish_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_idle_warmup_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_session_rotation_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    caption_profile: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    brief: Mapped[str] = mapped_column(Text, default="")
    hold_for_review: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_spend_cap_usd: Mapped[float] = mapped_column(Float, default=0.0)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    jobs: Mapped[list["PostJob"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class PostJob(Base):
    __tablename__ = "post_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    account: Mapped[Account] = relationship(back_populates="jobs")

    source_video_path: Mapped[str] = mapped_column(String(500))
    post_type: Mapped[PostType] = mapped_column(
        Enum(PostType, native_enum=False), default=PostType.reel, index=True
    )
    caption_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    privacy: Mapped[str] = mapped_column(String(32), default="public")
    permalink: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    scheduled_for: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[PostJobStatus] = mapped_column(
        Enum(PostJobStatus, native_enum=False), default=PostJobStatus.queued, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PostLog(Base):
    __tablename__ = "post_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("post_jobs.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)

    media_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    media_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    post_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    final_video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    final_caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_stats_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    view_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    like_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    play_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    save_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    share_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_stats_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyStat(Base):
    __tablename__ = "daily_stats"
    __table_args__ = (UniqueConstraint("account_id", "date_key", name="uq_account_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    date_key: Mapped[str] = mapped_column(String(10), index=True)
    posts_count: Mapped[int] = mapped_column(Integer, default=0)
    failures_count: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    level: Mapped[EventLevel] = mapped_column(Enum(EventLevel, native_enum=False), default=EventLevel.info, index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class DiagnosticRun(Base):
    __tablename__ = "diagnostic_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[DiagnosticRunKind] = mapped_column(Enum(DiagnosticRunKind, native_enum=False), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("post_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[DiagnosticRunStatus] = mapped_column(
        Enum(DiagnosticRunStatus, native_enum=False), default=DiagnosticRunStatus.running, index=True
    )
    lines_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PanelOperator(Base):
    """Panel login credentials for sub-admins (operators)."""

    __tablename__ = "panel_operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PanelSettings(Base):
    """Singleton panel gate settings (id must stay 1)."""

    __tablename__ = "panel_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_path: Mapped[str] = mapped_column(String(200))
    master_password_hash: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    admin_notes: Mapped[str] = mapped_column(Text, default="")
    llm_gateway_token: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    llm_gateway_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


def _loads(raw: str, fallback: object) -> object:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


class MediaAsset(Base):
    """A clip or soundtrack in the library (upload / generated / composed)."""

    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(512), unique=True)
    kind: Mapped[AssetKind] = mapped_column(
        Enum(AssetKind, native_enum=False), default=AssetKind.video, index=True
    )
    source: Mapped[AssetSource] = mapped_column(
        Enum(AssetSource, native_enum=False), default=AssetSource.upload
    )
    label: Mapped[str] = mapped_column(String(120), default="")
    generator: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def available(self) -> bool:
        return self.file_removed_at is None

    @property
    def is_synthetic(self) -> bool:
        return self.source in (AssetSource.generated, AssetSource.composed)


class PlanJob(Base):
    __tablename__ = "plan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, native_enum=False), default=PipelineStatus.queued, index=True
    )
    count: Mapped[int] = mapped_column(Integer, default=5)
    duration_s: Mapped[float] = mapped_column(Float, default=5.0)
    auto_schedule: Mapped[bool] = mapped_column(Boolean, default=True)
    spread_over_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    planned: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    account: Mapped["Account"] = relationship()


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    backend: Mapped[str] = mapped_column(String(32), default="auto")
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, native_enum=False), default=PipelineStatus.queued, index=True
    )
    duration_s: Mapped[float] = mapped_column(Float, default=5.0)
    width: Mapped[int] = mapped_column(Integer, default=720)
    height: Mapped[int] = mapped_column(Integer, default=1280)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    post_title: Mapped[str] = mapped_column(String(255), default="")
    post_description: Mapped[str] = mapped_column(Text, default="")
    post_tags: Mapped[str] = mapped_column(Text, default="")
    auto_schedule: Mapped[bool] = mapped_column(Boolean, default=False)
    post_group: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    shot_index: Mapped[int] = mapped_column(Integer, default=0)
    plan_job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plan_jobs.id"), nullable=True, index=True)
    post_audio_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    stage: Mapped[str] = mapped_column(String(48), default="")
    queue_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    input_mode: Mapped[str] = mapped_column(String(32), default="text_only")
    reference_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    asset: Mapped[Optional["MediaAsset"]] = relationship(foreign_keys=[asset_id])
    post_audio: Mapped[Optional["MediaAsset"]] = relationship(foreign_keys=[post_audio_asset_id])


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    plan_job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plan_jobs.id"), nullable=True, index=True)
    trigger: Mapped[RunTrigger] = mapped_column(
        Enum(RunTrigger, native_enum=False), default=RunTrigger.job, index=True
    )
    backend: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[str] = mapped_column(Text, default="")
    ideas_json: Mapped[str] = mapped_column(Text, default="[]")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    questions_json: Mapped[str] = mapped_column(Text, default="[]")
    requested: Mapped[int] = mapped_column(Integer, default=0)
    returned: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    retried: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    account: Mapped["Account"] = relationship()

    @property
    def ideas(self) -> list:
        return _loads(self.ideas_json, [])  # type: ignore[return-value]

    @property
    def sources(self) -> list:
        return _loads(self.sources_json, [])  # type: ignore[return-value]

    @property
    def questions(self) -> list:
        return _loads(self.questions_json, [])  # type: ignore[return-value]


class Clarification(Base):
    __tablename__ = "clarifications"
    __table_args__ = (UniqueConstraint("account_id", "question_key", name="uq_clarification"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    agent_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    question: Mapped[str] = mapped_column(Text, default="")
    question_key: Mapped[str] = mapped_column(String(200), default="")
    why: Mapped[str] = mapped_column(Text, default="")
    assumed: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answered_by: Mapped[str] = mapped_column(String(64), default="")
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    asked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    @property
    def open(self) -> bool:
        return self.answer is None and not self.dismissed


def question_key(question: str) -> str:
    kept = "".join(ch if ch.isalnum() else " " for ch in question.casefold())
    return " ".join(kept.split())[:200]


class PromptPreset(Base):
    __tablename__ = "prompt_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    brief: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ChannelSource(Base):
    __tablename__ = "channel_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind, native_enum=False))
    value: Mapped[str] = mapped_column(String(1000))
    label: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_status: Mapped[str] = mapped_column(String(200), default="")
    last_read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Composition(Base):
    __tablename__ = "compositions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, native_enum=False), default=PipelineStatus.queued, index=True
    )
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    fps: Mapped[int] = mapped_column(Integer, default=30)
    audio_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    audio_fade_out_s: Mapped[float] = mapped_column(Float, default=1.5)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    post_title: Mapped[str] = mapped_column(String(255), default="")
    post_description: Mapped[str] = mapped_column(Text, default="")
    post_tags: Mapped[str] = mapped_column(Text, default="")
    auto_schedule: Mapped[bool] = mapped_column(Boolean, default=False)
    post_group: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    output_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    clips: Mapped[list["CompositionClip"]] = relationship(
        back_populates="composition",
        cascade="all, delete-orphan",
        order_by="CompositionClip.position",
    )
    audio: Mapped[Optional["MediaAsset"]] = relationship(foreign_keys=[audio_asset_id])
    output: Mapped[Optional["MediaAsset"]] = relationship(foreign_keys=[output_asset_id])


class CompositionClip(Base):
    __tablename__ = "composition_clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("compositions.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("media_assets.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)

    composition: Mapped["Composition"] = relationship(back_populates="clips")
    asset: Mapped["MediaAsset"] = relationship()


class WorkerBeat(Base):
    """Heartbeat from the agent/worker loop so the panel can tell idle from dead."""

    __tablename__ = "worker_beats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, default="worker")
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    period_seconds: Mapped[float] = mapped_column(Float, default=20.0)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
