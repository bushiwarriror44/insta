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
* :func:`geo_verify` — fetch the country code reported by an IP-geo
  service for the proxy's egress IP and compare with the operator-provided
  ``proxy.country``. We *warn* on mismatch (some providers route via
  multiple countries) but do not auto-disable.
* In-process 10-minute cache (:func:`health_check_cached`) — the worker
  now hits the cache for back-to-back jobs instead of pinging the network
  on every claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Proxy
from app.geo.country_codes import countries_mismatch, normalize_country_code
from app.logging_setup import get_logger

logger = get_logger(__name__)


class ProxyError(Exception):
    pass


@dataclass(frozen=True)
class HealthSnapshot:
    ok: bool
    ip: str | None
    country: str | None
    instagram_reachable: bool
    instagram_login_reachable: bool
    checked_at: datetime


_CHROME_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_INSTAGRAM_LOGIN_CHECK_URL = "https://www.instagram.com/accounts/login/"


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


_CACHE_TTL = timedelta(minutes=10)
_HEALTH_CACHE: dict[str, HealthSnapshot] = {}
_CACHE_LOCK = Lock()


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
        raise ProxyError(f"Proxy {_mask(proxy_url)} unhealthy: {exc}") from exc


def reach_instagram(proxy_url: str, timeout: int | None = None) -> bool:
    """Confirm the proxy can reach Instagram itself (TLS-only).

    We hit a public Instagram endpoint that responds without auth. Any
    2xx/3xx/4xx response is fine — what we are *really* checking is whether
    the TLS handshake succeeds via this proxy. If the egress is blocked at
    the network level we'll get a connect error here even though :func:`health_check`
    against ipify passed.
    """
    timeout = timeout or settings.proxy_health_timeout_sec
    targets = (
        "https://i.instagram.com/api/v1/zr/dual_tokens/",
        "https://www.instagram.com/data/manifest.json",
    )
    last_exc: Exception | None = None
    for url in targets:
        try:
            with httpx.Client(
                proxy=proxy_url,
                timeout=timeout,
                transport=httpx.HTTPTransport(retries=0),
                follow_redirects=False,
            ) as client:
                resp = client.get(url, headers={"User-Agent": "Instagram 351.1.0.39.105 Android"})
                # Anything that came back from IG (even 4xx) is "reachable".
                if resp.status_code < 500:
                    return True
                last_exc = RuntimeError(f"http {resp.status_code}")
        except (httpx.HTTPError, OSError) as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise ProxyError(f"Proxy {_mask(proxy_url)} cannot reach Instagram: {last_exc}")
    return False


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


def geo_verify(proxy_url: str, timeout: int | None = None) -> str | None:
    """Return the country code (ISO-2) the proxy's egress IP resolves to."""
    timeout = timeout or settings.proxy_health_timeout_sec
    try:
        with httpx.Client(
            proxy=proxy_url,
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
            follow_redirects=True,
        ) as client:
            resp = client.get("https://ipapi.co/country/")
            if resp.status_code == 200:
                value = resp.text.strip().upper()
                # ipapi returns 2-3 char codes; ignore obvious error bodies.
                if value and len(value) <= 8 and value.isalpha():
                    return value
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("proxy.geo_verify_failed", error=str(exc))
    return None


def health_check_cached(
    proxy_url: str,
    *,
    force: bool = False,
    check_login_page: bool = True,
) -> HealthSnapshot:
    """Run :func:`health_check` + :func:`reach_instagram` with a 10-min cache.

    Used by the worker before each publish: cuts redundant ipify+IG pings
    when several jobs claim the same proxy back-to-back, while still
    refreshing once per cache window so a slow-degrading proxy is caught.
    """
    now = datetime.now(timezone.utc)
    if not force:
        with _CACHE_LOCK:
            cached = _HEALTH_CACHE.get(proxy_url)
            if cached and now - cached.checked_at < _CACHE_TTL:
                if cached.ok:
                    return cached
                # Negative cache: re-check after TTL/2 to give bad proxies
                # a faster recovery path.
                if now - cached.checked_at < _CACHE_TTL / 2:
                    return cached

    ip = None
    ok = True
    ig_ok = False
    ig_login_ok = False
    country = None
    try:
        data = health_check(proxy_url)
        ip = data.get("ip") or None
    except ProxyError:
        ok = False

    if ok:
        try:
            ig_ok = reach_instagram(proxy_url)
        except ProxyError:
            ok = False
            ig_ok = False

    if ok:
        if check_login_page:
            ig_login_ok, login_status = reach_instagram_login_page(proxy_url)
            if login_status is not None and login_status >= 400:
                logger.warning(
                    "proxy.login_page_http_error",
                    status=login_status,
                )
        else:
            with _CACHE_LOCK:
                prev = _HEALTH_CACHE.get(proxy_url)
            ig_login_ok = prev.instagram_login_reachable if prev else False

    if ok:
        country = geo_verify(proxy_url)

    snapshot = HealthSnapshot(
        ok=ok,
        ip=ip,
        country=country,
        instagram_reachable=ig_ok,
        instagram_login_reachable=ig_login_ok,
        checked_at=now,
    )
    with _CACHE_LOCK:
        _HEALTH_CACHE[proxy_url] = snapshot
    if not snapshot.ok:
        raise ProxyError(f"Proxy {_mask(proxy_url)} unhealthy (cached)")
    return snapshot


def health_check_record(db: Session, proxy: Proxy) -> tuple[bool, HealthSnapshot | None, str | None]:
    """Run a full health check and persist the result on the Proxy row.

    Returns ``(is_healthy, snapshot, error_message)``.
    """
    try:
        snapshot = health_check_cached(proxy.url, force=True)
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
        if countries_mismatch(proxy.country, snapshot.country):
            logger.warning(
                "proxy.geo_mismatch",
                label=proxy.label,
                advertised=proxy.country,
                actual=snapshot.country,
            )
    db.commit()
    logger.info(
        "proxy.healthy",
        label=proxy.label,
        ip=proxy.last_known_ip,
        country=snapshot.country,
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
