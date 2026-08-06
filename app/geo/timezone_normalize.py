"""Normalize proxy/account timezone strings for Playwright (IANA IDs only)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.geo.country_codes import normalize_country_code

# Default IANA timezone per country when proxy timezone is missing or invalid.
_COUNTRY_DEFAULT_IANA: dict[str, str] = {
    "US": "America/New_York",
    "GB": "Europe/London",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "ES": "Europe/Madrid",
    "IT": "Europe/Rome",
    "PL": "Europe/Warsaw",
    "NL": "Europe/Amsterdam",
    "BR": "America/Sao_Paulo",
    "MX": "America/Mexico_City",
    "TR": "Europe/Istanbul",
    "AE": "Asia/Dubai",
    "IN": "Asia/Kolkata",
    "ID": "Asia/Jakarta",
    "TH": "Asia/Bangkok",
    "JP": "Asia/Tokyo",
    "RU": "Europe/Moscow",
    "UA": "Europe/Kyiv",
    "KZ": "Asia/Almaty",
    "CA": "America/Toronto",
    "AU": "Australia/Sydney",
}

# Fallback when only a numeric UTC offset is known (no country).
_OFFSET_HOURS_TO_IANA: dict[int, str] = {
    -8: "America/Los_Angeles",
    -7: "America/Denver",
    -6: "America/Chicago",
    -5: "America/New_York",
    0: "UTC",
    1: "Europe/Berlin",
    2: "Europe/Helsinki",
    3: "Europe/Moscow",
    4: "Asia/Dubai",
    5: "Asia/Karachi",
    6: "Asia/Almaty",
    7: "Asia/Bangkok",
    8: "Asia/Shanghai",
    9: "Asia/Tokyo",
}

_OFFSET_RE = re.compile(
    r"(?:(?:UTC|GMT)\s*([+-]?\d{1,2})(?::(\d{2}))?)|([+-]?\d{1,2})\s*(?:UTC|GMT)",
    re.IGNORECASE,
)


def _is_valid_iana(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def _parse_offset_hours(raw: str) -> int | None:
    """Parse '+9 UTC', 'UTC+9', 'GMT-5' into whole-hour offset."""
    m = _OFFSET_RE.search(raw.strip())
    if not m:
        return None
    if m.group(1) is not None:
        hours = int(m.group(1))
        minutes = int(m.group(2) or 0)
    else:
        hours = int(m.group(3))
        minutes = 0
    if minutes >= 30:
        hours += 1 if hours >= 0 else -1
    return hours


def normalize_playwright_timezone(
    tz: str | None,
    *,
    country: str | None = None,
) -> str:
    """Return a Playwright-compatible IANA timezone ID.

    Dolphin and some proxy providers use values like ``+9 UTC`` which Playwright
    rejects. When the value is not valid IANA we prefer the country default
    (geo consistency), then numeric offset mapping, then ``UTC``.
    """
    cc = normalize_country_code(country)
    country_default = _COUNTRY_DEFAULT_IANA.get(cc or "", "UTC") if cc else "UTC"

    if not tz or not str(tz).strip():
        return country_default

    raw = str(tz).strip()
    if _is_valid_iana(raw):
        return raw

    if cc and cc in _COUNTRY_DEFAULT_IANA:
        return _COUNTRY_DEFAULT_IANA[cc]

    offset = _parse_offset_hours(raw)
    if offset is not None:
        return _OFFSET_HOURS_TO_IANA.get(offset, "UTC")

    return "UTC"


def is_placeholder_timezone(tz: str | None) -> bool:
    """True when timezone is empty or the default ``UTC`` stub from forms/API."""
    if tz is None:
        return True
    raw = str(tz).strip()
    return not raw or raw.upper() == "UTC"


def timezone_from_proxy(
    proxy_tz: str | None,
    country: str | None = None,
) -> str:
    """Resolve the IANA timezone that should be used for an account bound to a proxy.

    Empty / ``UTC`` on the proxy is treated as unset so the country default applies.
    """
    if is_placeholder_timezone(proxy_tz):
        return normalize_playwright_timezone(None, country=country)
    return normalize_playwright_timezone(proxy_tz, country=country)


def iana_utc_offset_seconds(
    tz_id: str,
    *,
    at: datetime | None = None,
) -> int:
    """Return UTC offset in seconds for an IANA zone at *at* (default: now UTC)."""
    when = at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    zi = ZoneInfo(tz_id)
    local = when.astimezone(zi)
    offset = local.utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds())
