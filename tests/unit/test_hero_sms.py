"""Hero SMS handler client and API routes."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import hero_sms as hs


def test_normalize_prices_sorts_in_stock_first():
    raw = {
        "10": {"ig": {"cost": 0.2, "count": 0, "physicalCount": 0}},
        "52": {"ig": {"cost": 0.05, "count": 5, "physicalCount": 0}},
        "16": {"ig": {"cost": 0.08, "count": 2, "physicalCount": 0}},
    }
    rows = hs.normalize_prices(raw, service="ig")
    assert [r["country_id"] for r in rows] == [52, 16, 10]
    assert rows[0]["count"] == 5


def test_parse_balance_from_text():
    assert hs.parse_balance(hs._parse_text_body("ACCESS_BALANCE:12.34")) == 12.34


def test_phone_to_e164():
    assert hs.phone_to_e164("79001234567") == "+79001234567"
    assert hs.phone_to_e164("+7900") == "+7900"


def test_raise_no_numbers_payload():
    with pytest.raises(hs.HeroSmsError, match="номер"):
        hs._raise_if_error_payload({"title": "NO_NUMBERS", "details": "x"}, http_status=404)


@patch("app.services.hero_sms.call_handler")
def test_status_v2_wraps(mock_call):
    mock_call.return_value = {"sms": {"code": "123456", "text": "code 123456", "dateTime": "t"}}
    out = hs.status_v2("k", "99")
    assert out["sms"]["code"] == "123456"


@pytest.fixture()
def auth_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "hero_sms_api_key", "hero-test-key", raising=True)
    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return __import__("fastapi.testclient").testclient.TestClient(app)


def _h():
    return {"Authorization": "Bearer secret-token"}


def test_status_without_key(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "hero_sms_api_key", "", raising=True)
    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    client = TestClient(app)
    res = client.get("/api/hero-sms/status", headers=_h())
    assert res.status_code == 200
    assert res.json()["configured"] is False


def test_prices_route(auth_client):
    raw = {"52": {"ig": {"cost": 0.05, "count": 3, "physicalCount": 0}}}
    with patch("app.services.hero_sms.prices", return_value=raw):
        res = auth_client.get("/api/hero-sms/prices?service=ig", headers=_h())
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "ig"
    assert len(body["rows"]) == 1
    assert body["rows"][0]["country_id"] == 52


def test_order_route(auth_client):
    payload = {
        "activationId": "316",
        "phoneNumber": "66912345678",
        "activationCost": 0.06,
        "countryCode": 52,
        "serviceCode": "ig",
        "canGetAnotherSms": True,
    }
    with patch("app.services.hero_sms.order_number", return_value=payload):
        res = auth_client.post(
            "/api/hero-sms/order",
            headers=_h(),
            json={"service": "ig", "country_id": 52},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["activation_id"] == "316"
    assert body["phone_e164"].startswith("+")
