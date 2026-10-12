"""Proxy management.

Sticky residential/mobile proxies are bound 1:1 to accounts. We never
hot-swap a proxy on a logged-in client (that triggers Instagram's
verification flow). When health-check fails, we mark the proxy unhealthy
and the worker pauses the affected account until ops investigates.

Anti-detection extensions (in addition to the basic IP-echo health check):

* :func:`reach_instagram` — anonymous TLS handshake against
  ``i.instagram.com``. Confirms the proxy isn't blocked at the egress for
  Instagram specifically (a proxy can return your IP via ipify just fine
  while being already SSL-blocked by IG).
* :func:`geo_lookup` / :func:`geo_verify` — fetch country + timezone from
  an IP-geo service for the proxy's egress IP. Empty ``proxy.country`` /
  ``proxy.timezone`` are auto-filled on full health check; operator-set
  values are never overwritten. We *warn* on country mismatch but do not
  auto-disable.
* In-process cache (:func:`health_check_cached`) — routine paths use
  :attr:`HealthCheckScope.MINIMAL` (ipify only, Instagram flags from cache).
  Full Instagram probes run only on explicit proxy check / connection test.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Proxy
from app.geo.country_codes import countries_mismatch, normalize_country_code
from app.geo.timezone_normalize import normalize_playwright_timezone
from app.logging_setup import get_logger

logger = get_logger(__name__)


class ProxyError(Exception):
    pass


class HealthCheckScope(str, Enum):
    """How aggressively :func:`health_check_cached` hits the network."""

    MINIMAL = "minimal"  # ipify only; reuse Instagram/login/geo from cache
    FULL = "full"  # ipify + IG API + login page + geo (manual checks only)


@dataclass(frozen=True)
class HealthSnapshot:
    ok: bool
    ip: str | None
    country: str | None
    instagram_reachable: bool
    instagram_login_reachable: bool
    checked_at: datetime
    instagram_login_http_status: int | None = None
    timezone: str | None = None


_CHROME_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_INSTAGRAM_LOGIN_CHECK_URL = "https://www.instagram.com/accounts/login/"

_CACHE_TTL = timedelta(minutes=30)
_RATE_LIMIT_LOGIN_CACHE_TTL = timedelta(hours=2)
_HEALTH_CACHE: dict[str, HealthSnapshot] = {}
_CACHE_LOCK = Lock()


def proxy_risk_score(snapshot: HealthSnapshot, *, advertised_country: str | None = None) -> float:
    """Compute a coarse 0..1 risk score from health signals."""
    score = 0.0
    if not snapshot.ok:
        return 1.0
    if not snapshot.instagram_reachable:
        score += 0.6
    if not snapshot.instagram_login_reachable:
        score += 0.35
    if not snapshot.ip:
        score += 0.2
    if countries_mismatch(advertised_country, snapshot.country):
        score += 0.25
    return min(1.0, score)


def _cache_ttl_for(snapshot: HealthSnapshot) -> timedelta:
    if snapshot.instagram_login_http_status == 429:
        return _RATE_LIMIT_LOGIN_CACHE_TTL
    if (
        snapshot.ok
        and snapshot.instagram_reachable
        and snapshot.instagram_login_reachable
    ):
        return _CACHE_TTL
    return _CACHE_TTL / 2


def _inherit_cached_instagram_fields(
    prev: HealthSnapshot | None,
) -> tuple[bool, bool, int | None, str | None, str | None]:
    if prev is None:
        # Unknown login reachability — do not assume the page is open (avoids auto-goto into 429).
        return True, False, None, None, None
    return (
        prev.instagram_reachable,
        prev.instagram_login_reachable,
        prev.instagram_login_http_status,
        prev.country,
        prev.timezone,
    )


def note_proxy_login_http_status(proxy_url: str, status: int) -> None:
    """Update in-memory health cache after a browser navigation sees HTTP *status*."""
    now = datetime.now(timezone.utc)
    with _CACHE_LOCK:
        cached = _HEALTH_CACHE.get(proxy_url)
        if cached is None:
            return

        _HEALTH_CACHE[proxy_url] = replace(
            cached,
            instagram_login_http_status=status,
            instagram_login_reachable=status < 400,
            checked_at=now,
        )


def health_check(proxy_url: str, timeout: int | None = None) -> dict[str, str]:
    """Verify the proxy works. Returns ``{"ip": ...}`` on success."""
    timeout = timeout or settings.proxy_health_timeout_sec
    try:
        with httpx.Client(
            proxy=proxy_url,
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
            follow_redirects=True,
        ) as client:
            response = client.get(settings.proxy_health_url)
            response.raise_for_status()
            data: dict[str, str]
            try:
                data = response.json()
            except ValueError:
                data = {"ip": response.text.strip()}
            return data
    except (httpx.HTTPError, OSError) as exc:
        raise ProxyError(f"Прокси {_mask(proxy_url)} недоступен: {exc}") from exc


def reach_instagram(proxy_url: str, timeout: int | None = None) -> bool:
    """Confirm the proxy can reach Instagram itself (TLS-only).

    We hit a public Instagram endpoint that responds without auth. Any
    2xx/3xx/4xx response is fine — what we are *really* checking is whether
    the TLS handshake succeeds via this proxy. If the egress is blocked at
    the network level we'll get a connect error here even though :func:`health_check`
    against ipify passed.
    """
    timeout = timeout or settings.proxy_health_timeout_sec
    url = "https://i.instagram.com/api/v1/zr/dual_tokens/"
    try:
        with httpx.Client(
            proxy=proxy_url,
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
            follow_redirects=False,
        ) as client:
            resp = client.get(url, headers={"User-Agent": "Instagram 351.1.0.39.105 Android"})
            if resp.status_code < 500:
                return True
            raise ProxyError(
                f"Прокси {_mask(proxy_url)} не достучался до Instagram: http {resp.status_code}"
            )
    except (httpx.HTTPError, OSError) as exc:
        raise ProxyError(
            f"Прокси {_mask(proxy_url)} не достучался до Instagram: {exc}"
        ) from exc


def reach_instagram_login_page(proxy_url: str, timeout: int | None = None) -> tuple[bool, int | None]:
    """Check whether the Instagram login page is reachable with a browser-like UA.

    Unlike :func:`reach_instagram`, this hits ``/accounts/login/`` with a Chrome
    desktop user-agent — closer to what headed Playwright uses.
    """
    timeout = timeout or settings.proxy_health_timeout_sec
    try:
        with httpx.Client(
            proxy=proxy_url,
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
            follow_redirects=True,
        ) as client:
            resp = client.get(
                _INSTAGRAM_LOGIN_CHECK_URL,
                headers={
                    "User-Agent": _CHROME_DESKTOP_UA,
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            return resp.status_code < 400, resp.status_code
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("proxy.login_page_unreachable", error=str(exc))
        return False, None


def geo_lookup(proxy_url: str, timeout: int | None = None) -> tuple[str | None, str | None]:
    """Return ``(country_code, iana_timezone)`` for the proxy's egress IP.

    Uses ``ipapi.co/json/`` so country and timezone come from one request.
    When timezone is missing or invalid, falls back to the country default
    via :func:`normalize_playwright_timezone`.
    """
    timeout = timeout or settings.proxy_health_timeout_sec
    try:
        with httpx.Client(
            proxy=proxy_url,
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
            follow_redirects=True,
        ) as client:
            resp = client.get("https://ipapi.co/json/")
            if resp.status_code != 200:
                return None, None
            try:
                data = resp.json()
            except ValueError:
                return None, None
            if not isinstance(data, dict):
                return None, None

            raw_cc = data.get("country_code") or data.get("country")
            country = normalize_country_code(str(raw_cc)) if raw_cc else None
            if country and (len(country) > 8 or not country.isalpha()):
                country = None

            tz_raw = data.get("timezone")
            tz_str = str(tz_raw).strip() if tz_raw else None
            timezone_name = normalize_playwright_timezone(tz_str, country=country)
            # Only keep a timezone when we have a country signal or a real IANA value.
            if not country and not tz_str:
                timezone_name = None
            return country, timezone_name
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("proxy.geo_lookup_failed", error=str(exc))
    return None, None


def geo_verify(proxy_url: str, timeout: int | None = None) -> str | None:
    """Return the country code (ISO-2) the proxy's egress IP resolves to."""
    country, _timezone = geo_lookup(proxy_url, timeout=timeout)
    return country


def health_check_cached(
    proxy_url: str,
    *,
    force: bool = False,
    scope: HealthCheckScope = HealthCheckScope.MINIMAL,
) -> HealthSnapshot:
    """Run proxy health with an in-memory cache.

    * ``MINIMAL`` (default) — only ipify; Instagram/login/geo flags are reused
      from cache. Used by worker, idle warmup, browser start.
    * ``FULL`` — ipify + one IG API probe + login page + geo. Manual checks only.
    """
    now = datetime.now(timezone.utc)
    if not force:
        with _CACHE_LOCK:
            cached = _HEALTH_CACHE.get(proxy_url)
            if cached:
                ttl = _cache_ttl_for(cached)
                if now - cached.checked_at < ttl:
                    if cached.ok:
                        return cached
                    if now - cached.checked_at < ttl / 2:
                        return cached

    with _CACHE_LOCK:
        prev = _HEALTH_CACHE.get(proxy_url)

    ip = None
    ok = True
    ig_ok, ig_login_ok, login_status, country, geo_timezone = _inherit_cached_instagram_fields(prev)
    try:
        data = health_check(proxy_url)
        ip = data.get("ip") or None
    except ProxyError:
        ok = False

    if ok and scope is HealthCheckScope.FULL:
        try:
            ig_ok = reach_instagram(proxy_url)
        except ProxyError:
            ok = False
            ig_ok = False

        if ok:
            skip_login_probe = (
                prev is not None
                and prev.instagram_login_http_status == 429
                and now - prev.checked_at < _RATE_LIMIT_LOGIN_CACHE_TTL
            )
            if skip_login_probe:
                ig_login_ok = prev.instagram_login_reachable
                login_status = prev.instagram_login_http_status
            else:
                ig_login_ok, login_status = reach_instagram_login_page(proxy_url)
                if login_status is not None and login_status >= 400:
                    logger.warning(
                        "proxy.login_page_http_error",
                        status=login_status,
                    )

        if ok:
            country, geo_timezone = geo_lookup(proxy_url)

    snapshot = HealthSnapshot(
        ok=ok,
        ip=ip,
        country=country,
        instagram_reachable=ig_ok,
        instagram_login_reachable=ig_login_ok,
        checked_at=now,
        instagram_login_http_status=login_status,
        timezone=geo_timezone,
    )
    with _CACHE_LOCK:
        _HEALTH_CACHE[proxy_url] = snapshot
    if not snapshot.ok:
        raise ProxyError(f"Прокси {_mask(proxy_url)} недоступен (кэш)")
    return snapshot


def health_check_record(db: Session, proxy: Proxy) -> tuple[bool, HealthSnapshot | None, str | None]:
    """Run a full health check and persist the result on the Proxy row.

    Returns ``(is_healthy, snapshot, error_message)``.
    """
    try:
        snapshot = health_check_cached(proxy.url, force=True, scope=HealthCheckScope.FULL)
    except ProxyError as exc:
        proxy.is_healthy = False
        proxy.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        err = str(exc)
        logger.warning("proxy.unhealthy", label=proxy.label, error=err)
        return False, None, err

    proxy.is_healthy = True
    proxy.last_checked_at = datetime.now(timezone.utc)
    proxy.last_known_ip = snapshot.ip or proxy.last_known_ip
    if snapshot.country:
        proxy.last_geo_country = snapshot.country
        if not (proxy.country or "").strip():
            proxy.country = normalize_country_code(snapshot.country)
        elif countries_mismatch(proxy.country, snapshot.country):
            logger.warning(
                "proxy.geo_mismatch",
                label=proxy.label,
                advertised=proxy.country,
                actual=snapshot.country,
            )
    if not (proxy.timezone or "").strip():
        if snapshot.timezone:
            proxy.timezone = snapshot.timezone
        elif proxy.country or snapshot.country:
            proxy.timezone = normalize_playwright_timezone(
                None, country=proxy.country or snapshot.country
            )
    db.commit()
    logger.info(
        "proxy.healthy",
        label=proxy.label,
        ip=proxy.last_known_ip,
        country=snapshot.country,
        timezone=proxy.timezone,
        instagram=snapshot.instagram_reachable,
        instagram_login=snapshot.instagram_login_reachable,
    )
    if not snapshot.instagram_reachable:
        return True, snapshot, "Instagram unreachable through proxy"
    if not snapshot.instagram_login_reachable:
        return True, snapshot, "Instagram login page unreachable through proxy"
    return True, snapshot, None


def upsert_proxy(
    db: Session,
    label: str,
    url: str,
    country: Optional[str] = None,
    timezone_name: Optional[str] = None,
    notes: Optional[str] = None,
) -> Proxy:
    if country is not None:
        country = normalize_country_code(country)
    proxy = db.query(Proxy).filter(Proxy.label == label).one_or_none()
    if proxy is None:
        proxy = Proxy(label=label, url=url, country=country, timezone=timezone_name, notes=notes)
        db.add(proxy)
    else:
        proxy.url = url
        if country is not None:
            proxy.country = country
        if timezone_name is not None:
            proxy.timezone = timezone_name
        if notes is not None:
            proxy.notes = notes
    db.commit()
    db.refresh(proxy)
    return proxy


def _mask(url: str) -> str:
    """Hide credentials when printing a proxy URL."""
    try:
        if "@" not in url:
            return url
        scheme_sep = url.split("://", 1)
        if len(scheme_sep) != 2:
            return url
        scheme, rest = scheme_sep
        host = rest.split("@", 1)[1]
        return f"{scheme}://***@{host}"
    except Exception:
        return "***"


def reset_health_cache() -> None:
    """Clear the health snapshot cache. Useful for tests and for ops to force
    a re-check from the CLI."""
    with _CACHE_LOCK:
        _HEALTH_CACHE.clear()
