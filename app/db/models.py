"""SQLAlchemy ORM models for the publisher service."""
from __future__ import annotations

import enum
from datetime import datetime
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


class Base(DeclarativeBase):
    pass


class AccountStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    challenge = "challenge"
    blocked = "blocked"
    cooldown = "cooldown"


class PostJobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    dead = "dead"
    cancelled = "cancelled"


class PostType(str, enum.Enum):
    reel = "reel"
    feed_photo = "feed_photo"
    feed_video = "feed_video"


class EventLevel(str, enum.Enum):
    info = "info"
    warn = "warn"
    error = "error"
    critical = "critical"


class DiagnosticRunKind(str, enum.Enum):
    connection_test = "connection_test"
    publish_job = "publish_job"
    first_login = "first_login"


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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(500))
    login_identifier: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email_password: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    totp_seed: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

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
