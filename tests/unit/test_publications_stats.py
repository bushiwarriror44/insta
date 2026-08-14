"""Unit tests for publication stats apply/refresh helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.publications.stats import apply_stats
from app.publisher.reels_publisher import MediaStats


def test_apply_stats_preserves_existing_counters_when_payload_partial():
    now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    post_log = SimpleNamespace(
        view_count=100,
        like_count=10,
        comment_count=2,
        play_count=120,
        save_count=5,
        share_count=1,
        raw_stats_json=None,
        last_stats_at=None,
    )
    stats = MediaStats(
        view_count=200,
        like_count=None,
        comment_count=None,
        play_count=None,
        save_count=None,
        share_count=None,
        raw_json='{"view_count": 200}',
    )

    apply_stats(post_log, stats, now=now)

    assert post_log.view_count == 200
    assert post_log.like_count == 10
    assert post_log.comment_count == 2
    assert post_log.play_count == 120
    assert post_log.save_count == 5
    assert post_log.share_count == 1
    assert post_log.raw_stats_json == '{"view_count": 200}'
    assert post_log.last_stats_at == now
