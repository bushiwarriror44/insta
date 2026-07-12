"""Tests for app.behavior.warmup_instagrapi."""
from __future__ import annotations

from instagrapi.exceptions import ClientError

from app.behavior import warmup_instagrapi as warmup_module
from tests.conftest import FakeInstagrapiClient, FakeMedia, FakeReelsTray


def _no_sleep(monkeypatch):
    monkeypatch.setattr(warmup_module, "think", lambda *a, **k: 0.0)


def test_light_warmup_calls_only_timeline(monkeypatch, app_env):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: False)
    client = FakeInstagrapiClient()
    counters = warmup_module.warmup(client, intensity="light")
    assert counters["feed_pages"] == 1
    assert counters["stories_viewed"] == 0
    assert counters["likes"] == 0
    assert counters["profiles_visited"] == 0
    names = [c[0] for c in client.calls]
    assert "get_timeline_feed" in names
    assert "media_like" not in names


def test_normal_warmup_with_stories(monkeypatch, app_env):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: True)
    client = FakeInstagrapiClient()
    client.reels_tray_response = FakeReelsTray()
    client.user_stories_response = [object(), object()]
    counters = warmup_module.warmup(client, intensity="normal")
    assert counters["feed_pages"] >= 1
    assert counters["stories_viewed"] >= 1


def test_heavy_warmup_attempts_like(monkeypatch, app_env):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: True)

    client = FakeInstagrapiClient()
    feed_media = FakeMedia(pk="999", code="X")
    feed_media.has_liked = False
    client.timeline_response = {"feed_items": [feed_media]}
    counters = warmup_module.warmup(client, intensity="heavy")
    assert counters["likes"] >= 1
    names = [c[0] for c in client.calls]
    assert "media_like" in names


def test_warmup_swallows_action_failures(monkeypatch, app_env):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: True)
    client = FakeInstagrapiClient()
    client.timeline_exc = ClientError("transient")
    counters = warmup_module.warmup(client, intensity="normal")
    assert counters["feed_pages"] == 0


def test_warmup_filters_already_liked(monkeypatch, app_env):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: True)
    client = FakeInstagrapiClient()
    only_liked = FakeMedia(pk="A")
    only_liked.has_liked = True
    client.timeline_response = {"feed_items": [only_liked]}
    counters = warmup_module.warmup(client, intensity="heavy")
    assert counters["likes"] == 0


# ---------------------------------------------------------------------------
# Extended action catalog: direct/news inbox, explore, media_seen.
# ---------------------------------------------------------------------------


def test_normal_warmup_opens_direct_inbox(monkeypatch, app_env):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: True)
    client = FakeInstagrapiClient()
    counters = warmup_module.warmup(client, intensity="normal")
    names = [c[0] for c in client.calls]
    assert counters["direct_inbox"] >= 1
    assert "direct_threads" in names


def test_heavy_warmup_hits_news_inbox_and_explore(monkeypatch, app_env):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: True)
    client = FakeInstagrapiClient()
    counters = warmup_module.warmup(client, intensity="heavy")
    names = [c[0] for c in client.calls]
    assert counters["news_inbox"] >= 1
    assert "news_inbox_v1" in names
    assert counters["explore"] >= 1
    assert "explore_page" in names


def test_warmup_marks_media_seen_before_like(monkeypatch, app_env):
    """The real Android client always records a ``media_seen`` ping before
    a like — our heavy-intensity warmup must follow the same order."""
    _no_sleep(monkeypatch)
    monkeypatch.setattr(warmup_module, "coin_flip", lambda *_: True)

    client = FakeInstagrapiClient()
    media = FakeMedia(pk="42")
    media.has_liked = False
    client.timeline_response = {"feed_items": [media]}

    warmup_module.warmup(client, intensity="heavy")
    names = [c[0] for c in client.calls]
    if "media_like" in names:
        assert "media_seen" in names
        assert names.index("media_seen") < names.index("media_like")
