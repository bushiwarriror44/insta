"""Tests for app.proxies.pool."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.config import settings
from app.db import Proxy
from app.proxies.pool import (
    HealthSnapshot,
    ProxyError,
    _mask,
    geo_verify,
    health_check,
    health_check_cached,
    health_check_record,
    reach_instagram,
    reset_health_cache,
    proxy_risk_score,
    upsert_proxy,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Health snapshots are process-global; clear between tests."""
    reset_health_cache()
    yield
    reset_health_cache()


@respx.mock
def test_health_check_success_returns_ip():
    respx.get(settings.proxy_health_url).mock(
        return_value=httpx.Response(200, json={"ip": "1.2.3.4"})
    )
    data = health_check("http://u:p@host:8000", timeout=5)
    assert data == {"ip": "1.2.3.4"}


@respx.mock
def test_health_check_non_json_returns_text_as_ip():
    respx.get(settings.proxy_health_url).mock(
        return_value=httpx.Response(200, text="9.9.9.9 ")
    )
    data = health_check("http://h:1", timeout=5)
    assert data["ip"] == "9.9.9.9"


@respx.mock
def test_health_check_5xx_raises_proxy_error():
    respx.get(settings.proxy_health_url).mock(return_value=httpx.Response(500))
    with pytest.raises(ProxyError):
        health_check("http://h:1", timeout=5)


@respx.mock
def test_health_check_record_updates_proxy_on_success(db_session, make_proxy):
    proxy = make_proxy()
    respx.get(settings.proxy_health_url).mock(
        return_value=httpx.Response(200, json={"ip": "5.5.5.5"})
    )
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        return_value=httpx.Response(200, text="{}")
    )
    respx.get("https://ipapi.co/country/").mock(
        return_value=httpx.Response(200, text="US")
    )
    ok, snapshot, err = health_check_record(db_session, proxy)
    assert ok is True
    assert snapshot is not None
    assert err is None
    db_session.refresh(proxy)
    assert proxy.is_healthy is True
    assert proxy.last_known_ip == "5.5.5.5"
    assert proxy.last_checked_at is not None
    assert proxy.last_geo_country == "US"


@respx.mock
def test_health_check_record_marks_unhealthy_on_failure(db_session, make_proxy):
    proxy = make_proxy()
    respx.get(settings.proxy_health_url).mock(return_value=httpx.Response(503))
    ok, _snapshot, err = health_check_record(db_session, proxy)
    assert ok is False
    assert err is not None
    db_session.refresh(proxy)
    assert proxy.is_healthy is False
    assert proxy.last_checked_at is not None


def test_upsert_proxy_inserts_then_updates(db_session):
    proxy_a = upsert_proxy(db_session, label="x", url="http://a:1", country="US")
    assert proxy_a.id is not None
    proxy_b = upsert_proxy(db_session, label="x", url="http://b:2", country="GB")
    assert proxy_b.id == proxy_a.id
    assert proxy_b.url == "http://b:2"
    assert proxy_b.country == "GB"


def test_upsert_proxy_only_updates_provided_fields(db_session):
    upsert_proxy(db_session, label="y", url="http://orig:1", country="US", notes="hello")
    after = upsert_proxy(db_session, label="y", url="http://orig:1")
    assert after.country == "US"
    assert after.notes == "hello"


def test_mask_hides_credentials():
    masked = _mask("http://user:pass@host.example:8000")
    assert "user" not in masked
    assert "pass" not in masked
    assert "host.example:8000" in masked
    assert "***" in masked


def test_mask_handles_no_credentials():
    assert _mask("http://host.example:8000") == "http://host.example:8000"


def test_mask_handles_garbage():
    # Should not raise on weird input.
    out = _mask("not-a-url")
    assert out == "not-a-url"


# ---------------------------------------------------------------------------
# Anti-detection extensions: Instagram reach, geo verification, cache.
# ---------------------------------------------------------------------------


@respx.mock
def test_reach_instagram_returns_true_on_2xx():
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        return_value=httpx.Response(200, json={})
    )
    assert reach_instagram("http://h:1", timeout=3) is True


@respx.mock
def test_reach_instagram_falls_back_on_first_failure():
    """If the first probe URL errors but the second 4xx replies, we count it
    as reachable (TLS handshake is what we are validating)."""
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        side_effect=httpx.ConnectTimeout("nope")
    )
    respx.get("https://www.instagram.com/data/manifest.json").mock(
        return_value=httpx.Response(401, text="auth required")
    )
    assert reach_instagram("http://h:1", timeout=3) is True


@respx.mock
def test_reach_instagram_raises_when_all_probes_fail():
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        side_effect=httpx.ConnectTimeout("nope")
    )
    respx.get("https://www.instagram.com/data/manifest.json").mock(
        side_effect=httpx.ConnectTimeout("nope")
    )
    with pytest.raises(ProxyError):
        reach_instagram("http://h:1", timeout=3)


@respx.mock
def test_geo_verify_returns_country_code():
    respx.get("https://ipapi.co/country/").mock(
        return_value=httpx.Response(200, text="DE\n")
    )
    assert geo_verify("http://h:1") == "DE"


@respx.mock
def test_geo_verify_returns_none_on_error():
    respx.get("https://ipapi.co/country/").mock(side_effect=httpx.ConnectError("x"))
    assert geo_verify("http://h:1") is None


@respx.mock
def test_health_check_cached_skips_network_within_ttl():
    respx.get(settings.proxy_health_url).mock(
        return_value=httpx.Response(200, json={"ip": "1.2.3.4"})
    )
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        return_value=httpx.Response(200, text="{}")
    )
    respx.get("https://ipapi.co/country/").mock(
        return_value=httpx.Response(200, text="US")
    )

    snap1 = health_check_cached("http://h:1")
    snap2 = health_check_cached("http://h:1")
    assert snap1.ip == snap2.ip == "1.2.3.4"
    # ipify route should have been hit only once thanks to the cache.
    ipify_route = next(
        r for r in respx.routes if "ipify" in str(r.pattern)
    )
    assert ipify_route.call_count == 1


@respx.mock
def test_health_check_cached_force_refresh_bypasses_cache():
    respx.get(settings.proxy_health_url).mock(
        return_value=httpx.Response(200, json={"ip": "1.2.3.4"})
    )
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        return_value=httpx.Response(200, text="{}")
    )
    respx.get("https://ipapi.co/country/").mock(
        return_value=httpx.Response(200, text="US")
    )
    health_check_cached("http://h:1")
    health_check_cached("http://h:1", force=True)
    ipify_route = next(
        r for r in respx.routes if "ipify" in str(r.pattern)
    )
    assert ipify_route.call_count == 2


@respx.mock
def test_geo_mismatch_does_not_disable_proxy(db_session, make_proxy):
    """Country mismatch is a *warning*, not a hard failure — some providers
    legitimately route via multiple countries."""
    proxy = make_proxy(country="DE")
    respx.get(settings.proxy_health_url).mock(
        return_value=httpx.Response(200, json={"ip": "1.2.3.4"})
    )
    respx.get("https://i.instagram.com/api/v1/zr/dual_tokens/").mock(
        return_value=httpx.Response(200, text="{}")
    )
    respx.get("https://ipapi.co/country/").mock(
        return_value=httpx.Response(200, text="NL")
    )
    ok, snapshot, err = health_check_record(db_session, proxy)
    assert ok is True
    assert snapshot is not None
    assert err is None
    db_session.refresh(proxy)
    assert proxy.last_geo_country == "NL"


def test_proxy_risk_score_detects_geo_mismatch():
    snap = HealthSnapshot(
        ok=True,
        ip="1.2.3.4",
        country="NL",
        instagram_reachable=True,
        checked_at=datetime.now(timezone.utc),
    )
    score = proxy_risk_score(snap, advertised_country="DE")
    assert 0.2 <= score <= 1.0
