"""Pre-publish warmup using the instagrapi Client.

Real users don't open the app and immediately upload. They scroll the
feed, watch a story or two, maybe like a post. We mimic that with cheap
authed reads and the occasional like, every action wrapped in a
lognormal sleep. Each action is probabilistic and can be skipped.

Failures here are non-fatal — the warmup is best-effort.
"""
from __future__ import annotations

import random
import time
from typing import Iterable

from instagrapi import Client
from instagrapi.exceptions import ClientError, FeedbackRequired

from app.behavior.humanizer import coin_flip, think
from app.logging_setup import get_logger

logger = get_logger(__name__)


def _safe(name: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ClientError, FeedbackRequired) as exc:
        logger.warning("warmup.action_failed", action=name, error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("warmup.action_unexpected", action=name, error=str(exc))
    return None


def _pick_media_for_like(timeline_items: Iterable, max_age_hours: float = 168.0):
    candidates = []
    for item in timeline_items:
        media = getattr(item, "media_or_ad", None) or item
        if media is None:
            continue
        like_status = getattr(media, "has_liked", False)
        if like_status:
            continue
        candidates.append(media)
    if not candidates:
        return None
    return random.choice(candidates)


# ---------------------------------------------------------------------------
# Extended action catalog.
#
# Real Instagram clients hit a wider surface than feed/stories — direct inbox,
# news inbox, explore, "media seen" beacons. Each of these is a low-cost read
# that, combined, makes the per-account traffic profile look more like a real
# user opening the app and just browsing.
# ---------------------------------------------------------------------------


def _direct_inbox(client: Client) -> bool:
    """Open the Direct messages inbox. Best-effort across instagrapi versions."""
    if hasattr(client, "direct_threads"):
        result = _safe("direct_threads", client.direct_threads, amount=5)
        return result is not None
    if hasattr(client, "direct_inbox"):
        result = _safe("direct_inbox", client.direct_inbox)
        return result is not None
    return False


def _news_inbox(client: Client) -> bool:
    """Activity feed (notifications screen)."""
    if hasattr(client, "news_inbox_v1"):
        result = _safe("news_inbox_v1", client.news_inbox_v1)
        return result is not None
    if hasattr(client, "private_request"):
        result = _safe("news_inbox_private", client.private_request, "news/inbox/")
        return result is not None
    return False


def _explore_page(client: Client) -> bool:
    if hasattr(client, "explore_page"):
        result = _safe("explore_page", client.explore_page)
        return result is not None
    if hasattr(client, "private_request"):
        result = _safe(
            "explore_private", client.private_request, "discover/topical_explore/"
        )
        return result is not None
    return False


def _mark_media_seen(client: Client, media_pks: list) -> bool:
    """Send a "seen" beacon for media we just rendered in the feed."""
    if not media_pks:
        return False
    payload = [{"media_id": str(pk), "ts": int(time.time())} for pk in media_pks]
    if hasattr(client, "media_seen"):
        return _safe("media_seen", client.media_seen, payload) is not None
    return False


def _view_story(client: Client, story_pk) -> bool:
    if hasattr(client, "story_seen"):
        return _safe("story_seen", client.story_seen, [story_pk]) is not None
    if hasattr(client, "media_seen"):
        return _safe(
            "story_via_media_seen",
            client.media_seen,
            [{"media_id": str(story_pk), "ts": int(time.time())}],
        ) is not None
    return False


def warmup(client: Client, intensity: str = "normal") -> dict[str, int]:
    """Run a warmup session.

    intensity:
        - "light": just one feed page, no likes, no stories.
        - "normal": 1-2 feed pages, maybe 1 story, maybe 1 like, maybe inbox.
        - "heavy": 2 pages, story tray scroll, 1-2 likes, profile peek,
          inbox + news inbox + explore.

    Returns a dict of per-action counters for logging.
    """
    counters = {
        "feed_pages": 0,
        "stories_viewed": 0,
        "likes": 0,
        "profiles_visited": 0,
        "media_seen": 0,
        "direct_inbox": 0,
        "news_inbox": 0,
        "explore": 0,
    }
    log = logger.bind(intensity=intensity)
    log.info("warmup.start")

    think(2.5, max_sec=8.0)

    # Direct inbox first — that is the screen most users glance at on app open.
    if intensity != "light" and coin_flip(0.55):
        if _direct_inbox(client):
            counters["direct_inbox"] += 1
            think(2.5, max_sec=8.0)

    feed_pages = {"light": 1, "normal": random.choice([1, 2]), "heavy": 2}.get(intensity, 1)
    timeline_items = []
    for page in range(feed_pages):
        result = _safe("feed_timeline", client.get_timeline_feed)
        if result:
            counters["feed_pages"] += 1
            try:
                items = list(result.get("feed_items", []))
            except AttributeError:
                items = []
            timeline_items.extend(items)
            # Imitate scrolling/viewing time before "marking seen".
            think(median_sec=3.0, max_sec=12.0)
            seen_pks = []
            for it in items[: random.randint(2, 6)]:
                media = getattr(it, "media_or_ad", None) or it
                pk = getattr(media, "pk", None) or getattr(media, "id", None)
                if pk:
                    seen_pks.append(pk)
            if _mark_media_seen(client, seen_pks):
                counters["media_seen"] += len(seen_pks)
        think(4.0, max_sec=15.0)

    if intensity != "light" and coin_flip(0.6):
        reels_tray = _safe("reels_tray", client.reels_tray)
        if reels_tray:
            tray_users = getattr(reels_tray, "tray", []) or []
            sample = tray_users[: random.randint(1, min(3, len(tray_users)) or 1)]
            for tray_item in sample:
                user_id = getattr(tray_item, "id", None) or getattr(tray_item, "user", None)
                if user_id is None:
                    continue
                think(2.0, max_sec=6.0)
                stories = _safe("user_stories", client.user_stories, int(getattr(user_id, "pk", user_id)))
                if stories:
                    counters["stories_viewed"] += len(stories)
                    # View time + occasional explicit story_seen ping.
                    think(3.0, max_sec=8.0)
                    if coin_flip(0.4):
                        first_story = stories[0]
                        pk = getattr(first_story, "pk", None) or getattr(first_story, "id", None)
                        if pk:
                            _view_story(client, pk)

    if intensity == "heavy" and coin_flip(0.5) and timeline_items:
        media = _pick_media_for_like(timeline_items)
        if media is not None:
            media_pk = getattr(media, "pk", None)
            if media_pk:
                think(3.0, max_sec=10.0)
                # Always send a "seen" before "like" — the real client does this.
                _mark_media_seen(client, [media_pk])
                think(1.5, max_sec=5.0)
                if _safe("media_like", client.media_like, media_pk):
                    counters["likes"] += 1

    if intensity != "light" and coin_flip(0.3):
        try:
            account_info = client.account_info()
            if account_info is not None:
                counters["profiles_visited"] += 1
        except ClientError as exc:
            logger.warning("warmup.profile_peek_failed", error=str(exc))

    if intensity == "heavy" and coin_flip(0.5):
        if _news_inbox(client):
            counters["news_inbox"] += 1
            think(2.0, max_sec=7.0)

    if intensity == "heavy" and coin_flip(0.4):
        if _explore_page(client):
            counters["explore"] += 1
            think(3.0, max_sec=10.0)

    think(2.5, max_sec=8.0)
    log.info("warmup.done", **counters)
    return counters
