"""Shared helpers for Instagram sessionid cookie extraction."""
from __future__ import annotations

from urllib.parse import unquote

MIN_SESSIONID_LEN = 31


def normalize_sessionid(value: str | None) -> str | None:
    """Strip and URL-decode sessionid (Dolphin often exports ``%3A`` instead of ``:``)."""
    if value is None:
        return None
    cleaned = unquote(value.strip())
    if len(cleaned) < MIN_SESSIONID_LEN:
        return None
    return cleaned


def _cookie_expires(item: dict) -> float:
    raw = item.get("expires")
    if raw is None:
        raw = item.get("expirationDate")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def sessionid_from_cookies_array(cookies: list) -> str | None:
    """Return the best Instagram ``sessionid`` from a cookies array.

    Prefers ``*.instagram.com`` domain, then later ``expires``, then longer
    value, then last occurrence (freshest from a live context often last).
    """
    candidates: list[tuple[int, float, int, int, str]] = []
    for idx, item in enumerate(cookies):
        if not isinstance(item, dict):
            continue
        if item.get("name") != "sessionid":
            continue
        raw_value = item.get("value")
        normalized = normalize_sessionid(raw_value if isinstance(raw_value, str) else None)
        if not normalized:
            continue
        domain = str(item.get("domain") or "").lower()
        domain_score = 1 if "instagram.com" in domain else 0
        expires = _cookie_expires(item)
        candidates.append((domain_score, expires, len(normalized), idx, normalized))
    if not candidates:
        return None
    best = max(candidates, key=lambda c: (c[0], c[1], c[2], c[3]))
    return best[4]
