"""Tests for app.behavior.humanizer."""
from __future__ import annotations

import random

from app.behavior import humanizer as hz


def test_lognormal_delay_zero_for_zero_median():
    assert hz.lognormal_delay(0) == 0.0


def test_lognormal_delay_within_max_cap():
    for _ in range(50):
        v = hz.lognormal_delay(median_sec=2.0, sigma=2.5, max_sec=5.0)
        assert 0.0 <= v <= 5.0


def test_lognormal_delay_non_negative():
    for _ in range(20):
        assert hz.lognormal_delay(median_sec=1.0) >= 0.0


def test_think_invokes_sleep_with_value(monkeypatch):
    seen = {}

    def _sleep(v):
        seen["v"] = v

    monkeypatch.setattr(hz.time, "sleep", _sleep)
    monkeypatch.setattr(hz, "lognormal_delay", lambda *a, **k: 1.234)
    out = hz.think(2.0)
    assert out == 1.234
    assert seen["v"] == 1.234


def test_think_skips_sleep_for_zero(monkeypatch):
    monkeypatch.setattr(hz, "lognormal_delay", lambda *a, **k: 0.0)
    called = {"n": 0}

    def _sleep(_):
        called["n"] += 1

    monkeypatch.setattr(hz.time, "sleep", _sleep)
    assert hz.think(2.0) == 0.0
    assert called["n"] == 0


def test_coin_flip_extremes(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.0)
    assert hz.coin_flip(0.5) is True
    monkeypatch.setattr(random, "random", lambda: 0.999)
    assert hz.coin_flip(0.5) is False
    assert hz.coin_flip(0.0) is False
    assert hz.coin_flip(1.0) is True


def test_jitter_seconds_zero_base():
    assert hz.jitter_seconds(0.0) == 0.0


def test_jitter_seconds_within_spread():
    base = 10.0
    for _ in range(50):
        v = hz.jitter_seconds(base, spread=0.2)
        assert 8.0 <= v <= 12.0
