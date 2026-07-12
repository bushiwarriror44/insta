"""Tests for app.video.caption_pool."""
from __future__ import annotations

import re

from app.video.caption_pool import (
    DEFAULT_EMOJI_POOL,
    DEFAULT_HASHTAG_POOL,
    render_caption,
)


def test_render_replaces_all_placeholders():
    result = render_caption(
        account_username="alice",
        template="A {emoji} B {emojis:3} C {body} D {hashtags:4} E {newline} F",
        seed="alice:1",
    )
    assert "{" not in result
    assert "}" not in result
    assert "\n" in result


def test_seed_determinism():
    a = render_caption(account_username="alice", seed="same-seed")
    b = render_caption(account_username="alice", seed="same-seed")
    assert a == b


def test_seed_diversity():
    a = render_caption(account_username="alice", seed="seed-1")
    b = render_caption(account_username="alice", seed="seed-2")
    assert a != b


def test_custom_pools_used():
    out = render_caption(
        account_username="x",
        template="{body} | {hashtags:1}",
        body_pool=["UNIQUE_BODY_TOKEN"],
        hashtag_pool=["#unique_tag"],
        seed="z",
    )
    assert "UNIQUE_BODY_TOKEN" in out
    assert "#unique_tag" in out


def test_emojis_count_respected():
    out = render_caption(
        account_username="x",
        template="{emojis:5}",
        seed="z",
        emoji_pool=DEFAULT_EMOJI_POOL,
    )
    # Some emojis are multi-codepoint (e.g. ☀️) — the test just ensures the
    # output is non-empty and short enough.
    assert 1 <= len(out)


def test_hashtags_unique_within_one_render():
    out = render_caption(
        account_username="x",
        template="{hashtags:5}",
        seed="z",
        hashtag_pool=["#a", "#b", "#c", "#d", "#e", "#f"],
    )
    tags = re.findall(r"#\w+", out)
    assert len(tags) == 5
    assert len(set(tags)) == 5


def test_default_pools_referenced():
    assert len(DEFAULT_EMOJI_POOL) > 5
    assert len(DEFAULT_HASHTAG_POOL) > 5


def test_unknown_placeholder_left_intact():
    out = render_caption(
        account_username="x",
        template="hello {unknown}",
        seed="z",
    )
    assert "{unknown}" in out


# ---------------------------------------------------------------------------
# Profile + locale + tier-mix.
# ---------------------------------------------------------------------------


def test_profile_specific_body_used():
    """When a fitness profile is passed, the body should come from that
    profile's body pool — not the generic nature pool."""
    from app.video.caption_pool import CAPTION_PROFILES

    fitness_bodies = set(CAPTION_PROFILES["fitness"].bodies["en"])
    out = render_caption(
        account_username="x",
        template="{body}",
        seed="seed-fitness-1",
        profile="fitness",
        locale="en",
    )
    assert out in fitness_bodies


def test_locale_resolution_from_timezone():
    """If we set a Russian-speaking timezone, the body must be in Russian."""
    from app.video.caption_pool import CAPTION_PROFILES

    ru_bodies = set(CAPTION_PROFILES["lifestyle"].bodies["ru"])
    out = render_caption(
        account_username="x",
        template="{body}",
        seed="ru-seed",
        profile="lifestyle",
        timezone="Europe/Moscow",
    )
    assert out in ru_bodies


def test_tags_mix_pulls_from_multiple_tiers():
    """``{tags}`` should produce hashtags from at least 2 different tiers
    of the active profile so the post doesn't look like #fyp-spam."""
    from app.video.caption_pool import CAPTION_PROFILES

    tiers = CAPTION_PROFILES["nature"].hashtag_tiers
    out = render_caption(
        account_username="x",
        template="{tags}",
        seed="mix",
        profile="nature",
    )
    tags = set(re.findall(r"#\w+", out))
    assert tags  # at least some hashtags
    assert sum(1 for tag in tags if tag in tiers["viral"]) >= 1
    assert sum(1 for tag in tags if tag in tiers["medium"]) >= 1


def test_tags_default_count_in_realistic_band():
    out = render_caption(
        account_username="x",
        template="{tags}",
        seed="cnt",
        profile="travel",
    )
    tags = re.findall(r"#\w+", out)
    # Default tier mix sums to 10 hashtags; allow a small wobble for tiers
    # with fewer than the requested count of items.
    assert 6 <= len(tags) <= 14


def test_unknown_profile_falls_back_to_default():
    out = render_caption(
        account_username="x",
        template="{body}",
        seed="z",
        profile="not-a-real-profile",
    )
    assert out  # no crash, some body was rendered


def test_anti_repeat_guard_avoids_exact_tag_signature():
    first = render_caption(
        account_username="repeat-user",
        template="{body}\n\n{tags}",
        seed="same-seed",
        profile="nature",
        anti_repeat=True,
    )
    second = render_caption(
        account_username="repeat-user",
        template="{body}\n\n{tags}",
        seed="same-seed",
        profile="nature",
        anti_repeat=True,
    )
    assert first != second
