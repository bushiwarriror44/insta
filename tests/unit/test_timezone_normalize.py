"""Tests for Playwright timezone normalization."""
from app.geo.timezone_normalize import normalize_playwright_timezone


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
