from __future__ import annotations

import pytest

from app.accounts.cookie_formats import import_cookies_data
from app.agent.planner import ContentIdea, PlanResult, Usage, build_prompt
from app.db.models import Account, GenerationJob, Platform, PostJob, PostType
from app.publisher.reels_publisher import TemporaryPublishError
from app.publisher.tiktok_publisher import _caption, publish_tiktok
from app.publisher.youtube_publisher import publish_youtube_short
from app.scheduler.worker import _account_platform
from app.services.planning import plan_for_channel
from app.services.scheduling import post_type_for, schedule_assets


def test_account_platform_defaults_instagram(make_account):
    account = make_account()
    assert _account_platform(account) is Platform.instagram
    assert post_type_for(account) is PostType.reel


def test_same_username_allowed_on_different_platforms(db_session, make_proxy):
    proxy = make_proxy()
    ig = Account(username="same", password="x", platform=Platform.instagram, proxy_id=proxy.id)
    yt = Account(username="same", password="", platform=Platform.youtube, proxy_id=proxy.id)
    db_session.add_all([ig, yt])
    db_session.commit()
    assert ig.id != yt.id


def test_youtube_and_tiktok_post_types(make_account):
    yt = make_account(username="ytchan", platform=Platform.youtube)
    tt = make_account(username="ttchan", platform=Platform.tiktok)
    assert post_type_for(yt) is PostType.youtube_short
    assert post_type_for(tt) is PostType.tiktok


def test_schedule_assets_creates_post_job(db_session, make_account):
    from app.config import settings
    from app.db.models import AssetKind, AssetSource, MediaAsset

    account = make_account()
    clip = settings.media_dir / "clip.mp4"
    clip.write_bytes(b"fake")
    asset = MediaAsset(
        filename="clip.mp4",
        kind=AssetKind.video,
        source=AssetSource.upload,
        label="clip",
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    jobs = schedule_assets(db_session, account, [asset], titles={asset.id: "Hello"})
    assert len(jobs) == 1
    assert jobs[0].title == "Hello"
    assert jobs[0].post_type is PostType.reel
    assert db_session.get(PostJob, jobs[0].id) is not None


def test_schedule_assets_fallback_respects_min_gap(db_session, make_account):
    from datetime import datetime, timedelta, timezone

    from freezegun import freeze_time

    from app.config import settings
    from app.db.models import AssetKind, AssetSource, MediaAsset, PostJobStatus

    with freeze_time("2026-03-15 12:00:00", tz_offset=0):
        account = make_account(
            min_gap_hours=12,
            daily_post_cap=3,
            active_hour_start=0,
            active_hour_end=23,
        )
        clip = settings.media_dir / "later.mp4"
        clip.write_bytes(b"fake")
        asset = MediaAsset(filename="later.mp4", kind=AssetKind.video, source=AssetSource.upload)
        now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        blocker = PostJob(
            account_id=account.id,
            source_video_path=str(clip),
            post_type=PostType.reel,
            scheduled_for=now + timedelta(hours=1),
            status=PostJobStatus.queued,
        )
        db_session.add_all([asset, blocker])
        db_session.commit()
        jobs = schedule_assets(db_session, account, [asset], days_ahead=1)
        fresh = [job for job in jobs if job.id != blocker.id]
        assert len(fresh) == 1
        when = fresh[0].scheduled_for
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        assert when >= now + timedelta(hours=13)


def test_schedule_assets_fallback_stays_inside_active_hours(db_session, make_account):
    from datetime import datetime, timezone

    from freezegun import freeze_time

    from app.config import settings
    from app.db.models import AssetKind, AssetSource, MediaAsset

    with freeze_time("2026-03-15 15:00:00", tz_offset=0):
        account = make_account(active_hour_start=10, active_hour_end=12, min_gap_hours=4, daily_post_cap=1)
        clip = settings.media_dir / "hours.mp4"
        clip.write_bytes(b"fake")
        asset = MediaAsset(filename="hours.mp4", kind=AssetKind.video, source=AssetSource.upload)
        db_session.add(asset)
        db_session.commit()
        jobs = schedule_assets(db_session, account, [asset], days_ahead=1)
        when = jobs[0].scheduled_for
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        assert when == datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)


def test_schedule_assets_fallback_respects_daily_cap(db_session, make_account):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from freezegun import freeze_time

    from app.config import settings
    from app.db.models import AssetKind, AssetSource, MediaAsset

    with freeze_time("2026-03-15 16:00:00", tz_offset=0):
        account = make_account(
            daily_post_cap=1,
            min_gap_hours=1,
            active_hour_start=0,
            active_hour_end=23,
            timezone="UTC",
        )
        account.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db_session.commit()
        assets = []
        for name in ("cap-a.mp4", "cap-b.mp4", "cap-c.mp4"):
            (settings.media_dir / name).write_bytes(b"fake")
            asset = MediaAsset(filename=name, kind=AssetKind.video, source=AssetSource.upload)
            db_session.add(asset)
            assets.append(asset)
        db_session.commit()
        jobs = schedule_assets(db_session, account, assets, days_ahead=1)
        tz = ZoneInfo("UTC")
        today = datetime(2026, 3, 15, tzinfo=timezone.utc).astimezone(tz).date()
        same_day = 0
        for job in jobs:
            when = job.scheduled_for
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when.astimezone(tz).date() == today:
                same_day += 1
        assert same_day == 1
        assert len(jobs) == 3


def test_second_schedule_does_not_exceed_daily_cap(db_session, make_account):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from freezegun import freeze_time

    from app.config import settings
    from app.db.models import AssetKind, AssetSource, MediaAsset

    with freeze_time("2026-03-15 16:00:00", tz_offset=0):
        account = make_account(
            daily_post_cap=1,
            min_gap_hours=1,
            active_hour_start=0,
            active_hour_end=23,
            timezone="UTC",
        )
        account.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db_session.commit()
        assets = []
        for name in ("again-a.mp4", "again-b.mp4"):
            (settings.media_dir / name).write_bytes(b"fake")
            asset = MediaAsset(filename=name, kind=AssetKind.video, source=AssetSource.upload)
            db_session.add(asset)
            assets.append(asset)
        db_session.commit()
        first = schedule_assets(db_session, account, [assets[0]], days_ahead=1)
        second = schedule_assets(db_session, account, [assets[1]], days_ahead=1)
        tz = ZoneInfo("UTC")
        today = datetime(2026, 3, 15, tzinfo=timezone.utc).date()
        same_day = 0
        for job in first + second:
            when = job.scheduled_for
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when.astimezone(tz).date() == today:
                same_day += 1
        assert same_day == 1
        assert len(first) + len(second) == 2


def test_schedule_assets_week_spreads_across_days(db_session, make_account, monkeypatch):
    from datetime import timezone

    from freezegun import freeze_time

    from app.config import settings
    from app.db.models import AssetKind, AssetSource, MediaAsset
    from app.scheduler import planner as planner_module

    monkeypatch.setattr(planner_module, "DAILY_SKIP_PROB", 0.0, raising=True)
    account = make_account(daily_post_cap=1, min_gap_hours=4.0)
    assets = []
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        path = settings.media_dir / name
        path.write_bytes(b"fake")
        asset = MediaAsset(filename=name, kind=AssetKind.video, source=AssetSource.upload, label=name)
        db_session.add(asset)
        assets.append(asset)
    db_session.commit()
    for asset in assets:
        db_session.refresh(asset)

    with freeze_time("2026-03-15 12:00:00", tz_offset=0):
        jobs = schedule_assets(db_session, account, assets, days_ahead=7)
    assert len(jobs) == 3
    days = set()
    for job in jobs:
        when = job.scheduled_for
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        days.add(when.date())
        hour = when.astimezone(timezone.utc).hour if when.tzinfo else when.hour
        assert 10 <= hour <= 22
    assert len(days) == 3


def test_schedule_assets_separates_two_accounts(db_session, make_account, monkeypatch):
    from datetime import datetime, timezone

    from freezegun import freeze_time

    from app.config import settings
    from app.db.models import AssetKind, AssetSource, MediaAsset
    from app.scheduler.planner import CROSS_ACCOUNT_SPREAD_MINUTES

    slot = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "app.services.scheduling.plan_slots_for_day",
        lambda *args, **kwargs: [slot],
    )
    accounts = [
        make_account(username="spread-a", timezone="UTC", active_hour_start=0, active_hour_end=23),
        make_account(username="spread-b", timezone="UTC", active_hour_start=0, active_hour_end=23),
    ]
    assets = []
    for name in ("spread-a.mp4", "spread-b.mp4"):
        path = settings.media_dir / name
        path.write_bytes(b"fake")
        asset = MediaAsset(filename=name, kind=AssetKind.video, source=AssetSource.upload, label=name)
        db_session.add(asset)
        assets.append(asset)
    db_session.commit()
    for asset in assets:
        db_session.refresh(asset)

    with freeze_time("2026-10-10 12:00:00", tz_offset=0):
        first = schedule_assets(db_session, accounts[0], [assets[0]], days_ahead=1)
        second = schedule_assets(db_session, accounts[1], [assets[1]], days_ahead=1)

    delta = abs((first[0].scheduled_for - second[0].scheduled_for).total_seconds())
    assert delta > CROSS_ACCOUNT_SPREAD_MINUTES * 60


def test_youtube_publish_requires_session(tmp_path, monkeypatch):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(
        "app.publisher.youtube_publisher.playwright_state_path",
        lambda username, platform=None: tmp_path / "missing.json",
    )
    with pytest.raises(TemporaryPublishError):
        publish_youtube_short(
            username="u",
            video_path=video,
            title="t",
            proxy_url="http://127.0.0.1:1",
        )


def test_tiktok_publish_requires_session(tmp_path, monkeypatch):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(
        "app.publisher.tiktok_publisher.playwright_state_path",
        lambda username, platform=None: tmp_path / "missing.json",
    )
    with pytest.raises(TemporaryPublishError):
        publish_tiktok(
            username="u",
            video_path=video,
            title="t",
            proxy_url="http://127.0.0.1:1",
        )


def test_tiktok_caption_includes_hashtags():
    text = _caption("Hello", "desc", "fun, clip")
    assert "Hello" in text
    assert "#fun" in text
    assert "#clip" in text


def test_youtube_cookies_import_without_sessionid(app_env):
    result = import_cookies_data(
        "ytuser",
        [{"name": "SID", "value": "abc", "domain": ".youtube.com"}],
        platform="youtube",
    )
    assert result.playwright_state_saved
    assert result.session_id == ""
    from app.accounts.playwright_session import playwright_state_path

    assert playwright_state_path("ytuser", "youtube").exists()
    assert not playwright_state_path("ytuser").exists()


class StubAgent:
    name = "stub"

    def healthcheck(self):
        return True

    def plan(self, request):
        return PlanResult(
            ideas=[
                ContentIdea(
                    shots=["a misty pine ridge at dawn, slow drone push"],
                    title="Ridge at dawn",
                    description="Fog moving through pines.",
                    tags=["nature", "calm"],
                )
            ],
            questions=[],
            usage=Usage(model="stub", input_tokens=1, output_tokens=1),
            prompt=build_prompt(request),
            raw="{}",
        )


def test_plan_for_channel_writes_generation_jobs(db_session, make_account):
    account = make_account()
    account.brief = "calm nature, misty forests"
    db_session.commit()
    jobs = plan_for_channel(
        db_session,
        account,
        1,
        agent=StubAgent(),
        auto_schedule=False,
    )
    assert len(jobs) == 1
    assert jobs[0].account_id == account.id
    assert "pine ridge" in jobs[0].prompt
    stored = db_session.get(GenerationJob, jobs[0].id)
    assert stored is not None
    assert stored.post_title == "Ridge at dawn"
