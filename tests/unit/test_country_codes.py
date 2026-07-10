"""Tests for ISO country code normalization."""
from app.geo.country_codes import countries_match, countries_mismatch, normalize_country_code


def test_normalize_usa_to_us():
    assert normalize_country_code("USA") == "US"
    assert normalize_country_code("usa") == "US"


def test_normalize_uk_to_gb():
    assert normalize_country_code("UK") == "GB"


def test_normalize_iso2_unchanged():
    assert normalize_country_code("DE") == "DE"
    assert normalize_country_code("US") == "US"


def test_normalize_none_and_empty():
    assert normalize_country_code(None) is None
    assert normalize_country_code("") is None
    assert normalize_country_code("  ") is None


def test_countries_match_usa_and_us():
    assert countries_match("USA", "US") is True
    assert countries_mismatch("USA", "US") is False


def test_countries_mismatch_real_difference():
    assert countries_match("DE", "US") is False
    assert countries_mismatch("DE", "US") is True


def test_countries_match_when_either_missing():
    assert countries_match(None, "US") is True
    assert countries_match("US", None) is True
    assert countries_mismatch(None, "US") is False
