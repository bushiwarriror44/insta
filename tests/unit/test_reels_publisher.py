"""Tests for app.publisher.reels_publisher."""
from __future__ import annotations

import pytest
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientError,
    FeedbackRequired,
    PleaseWaitFewMinutes,
)

from app.accounts.device_factory import generate_fingerprint
from app.accounts.session_manager import AuthenticationError, HardCheckpoint
from app.publisher import reels_publisher as rp
from app.publisher.reels_publisher import (
    ActionCooldownError,
    HardPublishError,
    PublishResult,
    TemporaryPublishError,
    fetch_media_stats,
    publish_feed_photo,
    publish_feed_video,
    publish_reel,
)
from tests.conftest import FakeInstagrapiClient, FakeMedia


@pytest.fixture()
def fingerprint(app_env):
    return generate_fingerprint("US")


@pytest.fixture()
def fake_login_or_resume(monkeypatch):
    holder: dict[str, FakeInstagrapiClient] = {}

    def _factory(*args, **kwargs):
        client = FakeInstagrapiClient()
        holder["client"] = client
        return client

    monkeypatch.setattr(rp, "login_or_resume", _factory)
    return holder


@pytest.fixture()
def no_warmup(monkeypatch):
    monkeypatch.setattr(rp, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)


def test_publish_reel_happy_path(app_env, fingerprint, fake_login_or_resume, no_warmup):
    video = app_env.video_out_dir / "ok.mp4"
    video.write_bytes(b"x")

    result = publish_reel(
        username="alice",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        video_path=video,
        caption="hello",
    )
    assert isinstance(result, PublishResult)
    assert result.media_id == FakeMedia().pk
    assert result.media_code == FakeMedia().code
    assert result.final_caption == "hello"


def test_publish_feed_photo_uses_photo_upload(app_env, fingerprint, fake_login_or_resume, no_warmup):
    image = app_env.video_source_dir / "photo.jpg"
    image.write_bytes(b"x")
    result = publish_feed_photo(
        username="alice",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        image_path=image,
        caption="photo cap",
    )
    client = fake_login_or_resume["client"]
    names = [name for name, *_ in client.calls]
    assert "photo_upload" in names
    assert result.media_id == FakeMedia().pk


def test_publish_feed_video_uses_video_upload(app_env, fingerprint, fake_login_or_resume, no_warmup):
    video = app_env.video_source_dir / "feed.mp4"
    video.write_bytes(b"x")
    result = publish_feed_video(
        username="alice",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        video_path=video,
        caption="video cap",
    )
    client = fake_login_or_resume["client"]
    names = [name for name, *_ in client.calls]
    assert "video_upload" in names
    assert result.media_id == FakeMedia().pk


def test_fetch_media_stats_normalizes_counters(app_env, fingerprint, fake_login_or_resume):
    stats = fetch_media_stats(
        username="alice",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        media_id="123",
    )
    assert stats.view_count == 100
    assert stats.play_count == 120
    assert stats.like_count == 7
    assert stats.comment_count == 2
    assert stats.save_count == 1
    assert stats.share_count == 3
    assert stats.raw_json is not None


def test_missing_video_raises_hard(app_env, fingerprint):
    with pytest.raises(HardPublishError):
        publish_reel(
            username="alice",
            password="pw",
            fingerprint=fingerprint,
            proxy_url="http://p:1",
            video_path=app_env.video_out_dir / "nope.mp4",
            caption="x",
        )


def test_publish_rejects_missing_proxy_before_login(app_env, fingerprint, monkeypatch):
    called = {"login": False}

    def _factory(*args, **kwargs):
        called["login"] = True
        return FakeInstagrapiClient()

    monkeypatch.setattr(rp, "login_or_resume", _factory)
    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")

    with pytest.raises(HardPublishError, match="нужен прокси"):
        publish_reel(
            username="alice",
            password="pw",
            fingerprint=fingerprint,
            proxy_url=None,
            video_path=video,
            caption="x",
        )
    assert called["login"] is False


def test_login_hard_checkpoint_propagates(app_env, fingerprint, monkeypatch):
    def _raise(*a, **k):
        raise HardCheckpoint("locked")

    monkeypatch.setattr(rp, "login_or_resume", _raise)
    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    with pytest.raises(HardPublishError):
        publish_reel(
            username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
            video_path=video, caption="c",
        )


def test_login_rate_limited_is_temporary(app_env, fingerprint, monkeypatch):
    def _raise(*a, **k):
        raise AuthenticationError("rate-limited please wait")

    monkeypatch.setattr(rp, "login_or_resume", _raise)
    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    with pytest.raises(TemporaryPublishError):
        publish_reel(
            username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
            video_path=video, caption="c",
        )


def test_login_other_auth_error_is_hard(app_env, fingerprint, monkeypatch):
    def _raise(*a, **k):
        raise AuthenticationError("bad password")

    monkeypatch.setattr(rp, "login_or_resume", _raise)
    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    with pytest.raises(HardPublishError):
        publish_reel(
            username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
            video_path=video, caption="c",
        )


def _publish_with_upload_exc(app_env, fingerprint, monkeypatch, exc):
    client = FakeInstagrapiClient()
    client.clip_upload_exc = exc

    monkeypatch.setattr(rp, "login_or_resume", lambda *a, **k: client)
    monkeypatch.setattr(rp, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)
    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    return publish_reel(
        username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
        video_path=video, caption="c",
    )


def test_clip_upload_feedback_required_is_cooldown(app_env, fingerprint, monkeypatch):
    """FeedbackRequired must NOT hard-block the account anymore — it surfaces
    as :class:`ActionCooldownError` so the worker can apply a 24-48h cooldown."""
    with pytest.raises(ActionCooldownError):
        _publish_with_upload_exc(app_env, fingerprint, monkeypatch, FeedbackRequired("fb"))


def test_client_error_with_action_blocked_message_is_cooldown(app_env, fingerprint, monkeypatch):
    """Some IG errors arrive as bare ClientError with a throttling message; we
    upgrade those to ActionCooldownError too rather than letting the worker
    backoff-loop them indefinitely."""
    with pytest.raises(ActionCooldownError):
        _publish_with_upload_exc(
            app_env, fingerprint, monkeypatch,
            ClientError("This action was blocked. Try again later."),
        )


def test_clip_upload_challenge_is_hard(app_env, fingerprint, monkeypatch):
    with pytest.raises(HardPublishError):
        _publish_with_upload_exc(app_env, fingerprint, monkeypatch, ChallengeRequired("ch"))


def test_clip_upload_please_wait_is_temporary(app_env, fingerprint, monkeypatch):
    with pytest.raises(TemporaryPublishError):
        _publish_with_upload_exc(app_env, fingerprint, monkeypatch, PleaseWaitFewMinutes("rl"))


def test_clip_upload_client_error_is_temporary(app_env, fingerprint, monkeypatch):
    with pytest.raises(TemporaryPublishError):
        _publish_with_upload_exc(app_env, fingerprint, monkeypatch, ClientError("err"))


def test_warmup_failure_does_not_break_publish(app_env, fingerprint, monkeypatch):
    client = FakeInstagrapiClient()

    def _bad_warmup(*a, **k):
        raise RuntimeError("flaky")

    monkeypatch.setattr(rp, "login_or_resume", lambda *a, **k: client)
    monkeypatch.setattr(rp, "warmup", _bad_warmup)
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)

    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    result = publish_reel(
        username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
        video_path=video, caption="c", do_warmup=True,
    )
    assert isinstance(result, PublishResult)


def test_post_publish_settling_runs_after_success(app_env, fingerprint, monkeypatch):
    """After a successful upload, publisher should ping ``user_info_v1`` and
    ``get_timeline_feed`` to break the login-upload-vanish pattern."""
    client = FakeInstagrapiClient()
    monkeypatch.setattr(rp, "login_or_resume", lambda *a, **k: client)
    monkeypatch.setattr(rp, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)

    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    publish_reel(
        username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
        video_path=video, caption="c",
    )
    names = [name for name, *_ in client.calls]
    assert "clip_upload" in names
    upload_idx = names.index("clip_upload")
    later = names[upload_idx + 1:]
    assert "user_info_v1" in later
    assert "get_timeline_feed" in later


def test_settling_failure_does_not_break_publish(app_env, fingerprint, monkeypatch):
    """Settling probes are best-effort: if user_info_v1 raises, we still
    return the successful publish result."""
    client = FakeInstagrapiClient()

    def _boom(*a, **k):
        raise RuntimeError("ig flaked on probe")

    client.user_info_v1 = _boom

    monkeypatch.setattr(rp, "login_or_resume", lambda *a, **k: client)
    monkeypatch.setattr(rp, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)

    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    result = publish_reel(
        username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
        video_path=video, caption="c",
    )
    assert isinstance(result, PublishResult)


def test_totp_seed_forwarded_to_login(app_env, fingerprint, monkeypatch):
    """publish_reel should forward ``totp_seed`` to ``login_or_resume`` so
    the auth path can derive a 2FA code locally."""
    captured = {}

    def _factory(*args, **kwargs):
        captured.update(kwargs)
        return FakeInstagrapiClient()

    monkeypatch.setattr(rp, "login_or_resume", _factory)
    monkeypatch.setattr(rp, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)

    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    publish_reel(
        username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
        video_path=video, caption="c",
        totp_seed="JBSWY3DPEHPK3PXP",
    )
    assert captured["totp_seed"] == "JBSWY3DPEHPK3PXP"


def test_session_id_forwarded_to_login_when_session_file_exists(
    app_env, fingerprint, monkeypatch
):
    captured = {}

    def _factory(*args, **kwargs):
        captured.update(kwargs)
        return FakeInstagrapiClient()

    monkeypatch.setattr(rp, "login_or_resume", _factory)
    monkeypatch.setattr(rp, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)

    (app_env.sessions_dir / "session_a.json").write_text("{}", encoding="utf-8")
    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    publish_reel(
        username="a",
        password="p",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        video_path=video,
        caption="c",
        session_id="x" * 40,
    )
    assert captured["session_id"] == "x" * 40


def test_session_id_skipped_when_session_file_missing(
    app_env, fingerprint, monkeypatch
):
    """Web cookie in DB without mobile dump must not go to login_by_sessionid."""
    captured = {}

    def _factory(*args, **kwargs):
        captured.update(kwargs)
        return FakeInstagrapiClient()

    monkeypatch.setattr(rp, "login_or_resume", _factory)
    monkeypatch.setattr(rp, "warmup", lambda *a, **k: {})
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)

    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    publish_reel(
        username="a",
        password="p",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        video_path=video,
        caption="c",
        session_id="x" * 40,
    )
    assert captured["session_id"] is None


def test_fetch_media_stats_falls_back_to_media_info_v2(app_env, fingerprint, monkeypatch):
    client = FakeInstagrapiClient()
    client.media_info_exc = ClientError("ad tagged media")

    monkeypatch.setattr(rp, "login_or_resume", lambda *a, **k: client)

    stats = fetch_media_stats(
        username="alice",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        media_id="123",
    )
    names = [name for name, *_ in client.calls]
    assert "media_info" in names
    assert "media_info_v2" in names
    assert stats.view_count == 50
    assert stats.like_count == 3


def test_skip_warmup_when_disabled(app_env, fingerprint, monkeypatch):
    client = FakeInstagrapiClient()
    seen = {"called": 0}

    def _spy(*a, **k):
        seen["called"] += 1
        return {}

    monkeypatch.setattr(rp, "login_or_resume", lambda *a, **k: client)
    monkeypatch.setattr(rp, "warmup", _spy)
    monkeypatch.setattr(rp, "think", lambda *a, **k: 0.0)

    video = app_env.video_out_dir / "x.mp4"
    video.write_bytes(b"x")
    publish_reel(
        username="a", password="p", fingerprint=fingerprint, proxy_url="http://p:1",
        video_path=video, caption="c", do_warmup=False,
    )
    assert seen["called"] == 0
