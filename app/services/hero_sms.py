"""Hero SMS client API (sms-activate compatible handler)."""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings
from app.services.http import client as http_client

HERO_TIMEOUT = 30.0
USER_AGENT = "ReelsPublisherAdmin/1.0"

_ERROR_TITLES: dict[str, str] = {
    "NO_NUMBERS": "Нет свободных номеров для выбранной страны и сервиса. Попробуйте другую страну или позже.",
    "EARLY_CANCEL_DENIED": "Отмена пока недоступна — подождите минимальный срок активации.",
    "BAD_KEY": "Неверный API-ключ Hero SMS.",
    "NO_BALANCE": "Недостаточно средств на балансе Hero SMS.",
    "BAD_SERVICE": "Неизвестный код сервиса.",
    "BAD_STATUS": "Недопустимый статус для этой операции.",
}


class HeroSmsError(Exception):
    """User-facing Hero SMS failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _handler_url() -> str:
    return (settings.hero_sms_handler_url or "https://hero-sms.com/stubs/handler_api.php").rstrip("/")


def _explain_http_error(exc: BaseException) -> str:
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):
        return "Hero SMS не ответил вовремя (таймаут)."
    if isinstance(exc, httpx.ConnectError):
        return "Не удалось достучаться до Hero SMS API."
    text = str(exc).replace("\n", " ")[:160]
    return f"Ошибка Hero SMS: {text}" if text else "Ошибка Hero SMS."


def _message_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        title = str(payload.get("title") or "").strip()
        details = str(payload.get("details") or payload.get("detail") or "").strip()
        if title and title in _ERROR_TITLES:
            msg = _ERROR_TITLES[title]
            if details and details not in msg:
                return f"{msg} ({details})"
            return msg
        if details:
            return details
        if title:
            return title
    return ""


def _parse_text_body(body: str) -> Any:
    text = (body or "").strip()
    if not text:
        return None
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            pass
    if text.startswith("ACCESS_BALANCE:"):
        raw = text.split(":", 1)[1].strip()
        try:
            return {"balance": float(raw.replace(",", "."))}
        except ValueError:
            return {"balance_raw": raw}
    if text.startswith("ACCESS_NUMBER:"):
        parts = text.split(":")
        if len(parts) >= 3:
            return {
                "activationId": parts[1],
                "phoneNumber": parts[2],
                "legacy": True,
            }
    if text.startswith("STATUS_OK:"):
        code = text.split(":", 1)[1].strip()
        return {"sms": {"code": code, "text": code}, "legacy": True}
    known = _ERROR_TITLES.get(text)
    if known:
        raise HeroSmsError(known)
    if text in _ERROR_TITLES:
        raise HeroSmsError(_ERROR_TITLES[text])
    if text.startswith("BAD_") or text.startswith("NO_") or text.startswith("ERROR"):
        raise HeroSmsError(text.replace("_", " "))
    return text


def _raise_if_error_payload(payload: Any, *, http_status: int) -> None:
    if isinstance(payload, dict):
        title = str(payload.get("title") or "").strip()
        if title and title not in ("success",):
            raise HeroSmsError(_message_from_payload(payload) or title, status_code=http_status)
        status = str(payload.get("status") or "").strip().upper()
        if status in ("NO_NUMBERS", "ERROR"):
            raise HeroSmsError(_message_from_payload(payload) or status, status_code=http_status)
    if isinstance(payload, str) and payload.strip() and not payload.startswith("ACCESS_"):
        upper = payload.strip().upper()
        if upper in _ERROR_TITLES or upper.startswith("BAD_") or upper.startswith("NO_"):
            raise HeroSmsError(_ERROR_TITLES.get(upper, payload), status_code=http_status)


def call_handler(api_key: str, action: str, **params: Any) -> Any:
    key = (api_key or "").strip()
    if not key:
        raise HeroSmsError(
            "Не задан API-ключ Hero SMS. Укажите HERO_SMS_API_KEY или сохраните ключ в панели."
        )
    query: dict[str, Any] = {"action": action, "api_key": key}
    for k, v in params.items():
        if v is not None and v != "":
            query[k] = v
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"}
    try:
        with http_client(settings, timeout=HERO_TIMEOUT) as client:
            response = client.get(_handler_url(), params=query, headers=headers)
    except httpx.RequestError as exc:
        raise HeroSmsError(_explain_http_error(exc)) from exc

    body = (response.text or "").strip()
    payload: Any
    if body.startswith("{") or body.startswith("["):
        try:
            payload = response.json()
        except ValueError:
            payload = _parse_text_body(body)
    else:
        payload = _parse_text_body(body)

    if response.status_code == 401 or response.status_code == 403:
        raise HeroSmsError("Hero SMS отклонил ключ API.", status_code=response.status_code)
    if response.status_code == 404:
        _raise_if_error_payload(payload if isinstance(payload, dict) else {"title": "NO_NUMBERS"}, http_status=404)
    if response.status_code >= 400:
        msg = _message_from_payload(payload) if isinstance(payload, dict) else body[:200]
        raise HeroSmsError(msg or f"Hero SMS ответил HTTP {response.status_code}", status_code=response.status_code)

    _raise_if_error_payload(payload, http_status=response.status_code)
    return payload


def parse_balance(payload: Any) -> float | None:
    if isinstance(payload, dict) and "balance" in payload:
        try:
            return float(payload["balance"])
        except (TypeError, ValueError):
            return None
    if isinstance(payload, dict) and "balance_raw" in payload:
        try:
            return float(str(payload["balance_raw"]).replace(",", "."))
        except (TypeError, ValueError):
            return None
    return None


def balance(api_key: str) -> float | None:
    payload = call_handler(api_key, "getBalance")
    return parse_balance(payload)


def countries(api_key: str) -> Any:
    return call_handler(api_key, "getCountries")


def services_list(api_key: str) -> Any:
    return call_handler(api_key, "getServicesList")


def prices(api_key: str, *, service: str, country: int | None = None) -> Any:
    params: dict[str, Any] = {"service": service}
    if country is not None:
        params["country"] = country
    return call_handler(api_key, "getPrices", **params)


def normalize_prices(raw: Any, *, service: str) -> list[dict[str, Any]]:
    """Flatten getPrices JSON to rows for the UI."""
    if not isinstance(raw, dict):
        return []
    rows: list[dict[str, Any]] = []
    for country_key, services in raw.items():
        if not isinstance(services, dict):
            continue
        try:
            country_id = int(country_key)
        except (TypeError, ValueError):
            continue
        slot = services.get(service)
        if not isinstance(slot, dict):
            for code, data in services.items():
                if str(code).lower() == service.lower() and isinstance(data, dict):
                    slot = data
                    break
        if not isinstance(slot, dict):
            continue
        cost = slot.get("cost")
        count = slot.get("count")
        try:
            cost_f = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_f = None
        try:
            count_i = int(count) if count is not None else 0
        except (TypeError, ValueError):
            count_i = 0
        rows.append(
            {
                "country_id": country_id,
                "cost": cost_f,
                "count": count_i,
                "physical_count": int(slot.get("physicalCount") or 0),
            }
        )

    def sort_key(row: dict[str, Any]) -> tuple[int, float]:
        in_stock = 0 if (row.get("count") or 0) > 0 else 1
        cost = row.get("cost")
        cost_val = float(cost) if cost is not None else 1e9
        return (in_stock, cost_val)

    rows.sort(key=sort_key)
    return rows


def order_number(
    api_key: str,
    *,
    service: str,
    country: int,
    max_price: float | None = None,
    fixed_price: bool = False,
    operator: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "action": "getNumberV2",
        "service": service,
        "country": country,
    }
    if operator:
        params["operator"] = operator
    if max_price is not None:
        params["maxPrice"] = max_price
        if fixed_price:
            params["fixedPrice"] = 1
    payload = call_handler(api_key, "getNumberV2", **{k: v for k, v in params.items() if k != "action"})
    if isinstance(payload, dict) and payload.get("legacy"):
        return payload
    if isinstance(payload, dict) and payload.get("activationId"):
        return payload
    raise HeroSmsError("Неожиданный ответ Hero SMS при заказе номера.")


def status_v2(api_key: str, activation_id: str | int) -> dict[str, Any]:
    payload = call_handler(api_key, "getStatusV2", id=activation_id)
    if isinstance(payload, dict):
        return payload
    raise HeroSmsError("Неожиданный ответ статуса активации.")


def set_status(api_key: str, activation_id: str | int, status: int) -> str:
    payload = call_handler(api_key, "setStatus", id=activation_id, status=status)
    if isinstance(payload, str):
        return payload.strip()
    return str(payload)


def active_activations(api_key: str) -> list[dict[str, Any]]:
    payload = call_handler(api_key, "getActiveActivations")
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        aa = payload.get("activeActivations")
        if isinstance(aa, dict) and isinstance(aa.get("row"), dict):
            return [aa["row"]]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def history(api_key: str, *, size: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    import time

    end = int(time.time())
    start = end - 7 * 24 * 3600
    payload = call_handler(
        api_key,
        "getHistory",
        start=start,
        end=end,
        offset=offset,
        size=size,
    )
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def phone_to_e164(phone: str) -> str:
    p = str(phone or "").strip()
    if not p:
        return ""
    return p if p.startswith("+") else f"+{p.lstrip('+')}"
