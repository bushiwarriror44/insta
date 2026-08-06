"""Tests for Playwright timezone normalization and account/proxy sync helpers."""
from datetime import datetime, timezone

from app.geo.timezone_normalize import (
    iana_utc_offset_seconds,
    is_placeholder_timezone,
    normalize_playwright_timezone,
    timezone_from_proxy,
)


def test_valid_iana_passthrough():
    assert normalize_playwright_timezone("Europe/Berlin") == "Europe/Berlin"
    assert normalize_playwright_timezone("America/New_York") == "America/New_York"


def test_plus_nine_utc_with_us_country_uses_country_default():
    assert normalize_playwright_timezone("+9 UTC", country="US") == "America/New_York"


def test_plus_nine_utc_without_country_uses_offset():
    assert normalize_playwright_timezone("+9 UTC") == "Asia/Tokyo"


def test_utc_plus_nine_variant():
    assert normalize_playwright_timezone("UTC+9") == "Asia/Tokyo"


def test_empty_uses_country_default():
    assert normalize_playwright_timezone(None, country="DE") == "Europe/Berlin"
    assert normalize_playwright_timezone("", country="JP") == "Asia/Tokyo"


def test_garbage_falls_back_to_country():
    assert normalize_playwright_timezone("not-a-timezone", country="GB") == "Europe/London"


def test_is_placeholder_timezone():
    assert is_placeholder_timezone(None) is True
    assert is_placeholder_timezone("") is True
    assert is_placeholder_timezone("UTC") is True
    assert is_placeholder_timezone("utc") is True
    assert is_placeholder_timezone("  UTC  ") is True
    assert is_placeholder_timezone("Europe/Berlin") is False


def test_timezone_from_proxy_uses_country_when_proxy_utc():
    assert timezone_from_proxy("UTC", "PL") == "Europe/Warsaw"
    assert timezone_from_proxy(None, "DE") == "Europe/Berlin"


def test_timezone_from_proxy_keeps_explicit_iana():
    assert timezone_from_proxy("Europe/Warsaw", "DE") == "Europe/Warsaw"


def test_iana_utc_offset_seconds_warsaw_winter():
    # 2024-01-15: Europe/Warsaw is CET (UTC+1)
    at = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert iana_utc_offset_seconds("Europe/Warsaw", at=at) == 3600


def test_iana_utc_offset_seconds_warsaw_summer():
    at = datetime(2024, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert iana_utc_offset_seconds("Europe/Warsaw", at=at) == 7200
