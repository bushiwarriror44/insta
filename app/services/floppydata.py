"""Floppydata Client API v2 (rotating proxies)."""
from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.services.http import client as http_client

FLOPPY_TIMEOUT = 30.0


class FloppydataError(Exception):
    """User-facing Floppydata failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    return (settings.floppydata_base_url or "https://api.floppydata.net").rstrip("/")


def _explain_http_error(exc: BaseException) -> str:
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):
        return "Floppydata не ответил вовремя (таймаут)."
    if isinstance(exc, httpx.ConnectError):
        return "Не удалось достучаться до Floppydata API."
    text = str(exc).replace("\n", " ")[:160]
    return f"Ошибка Floppydata: {text}" if text else "Ошибка Floppydata."


def _request(
    method: str,
    path: str,
    *,
    api_key: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    key = (api_key or "").strip()
    if not key:
        raise FloppydataError("Не задан API-ключ Floppydata. Укажите FLOPPYDATA_API_KEY или сохраните ключ в панели.")
    url = f"{_base_url()}{path}"
    headers = {"X-Api-Key": key, "Accept": "application/json"}
    try:
        with http_client(settings, timeout=FLOPPY_TIMEOUT) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
            )
    except httpx.RequestError as exc:
        raise FloppydataError(_explain_http_error(exc)) from exc

    if response.status_code == 401 or response.status_code == 403:
        raise FloppydataError(
            "Floppydata отклонил ключ. Проверьте API key в app.floppydata.com/api-keys.",
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("detail") or payload.get("error") or "")
        except ValueError:
            detail = (response.text or "")[:200]
        msg = detail.strip() or f"Floppydata ответил HTTP {response.status_code}"
        raise FloppydataError(msg, status_code=response.status_code)

    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise FloppydataError("Floppydata вернул не-JSON ответ") from exc


def rotating_balance(api_key: str) -> dict[str, Any]:
    data = _request("GET", "/v2/proxy/rotating/balance", api_key=api_key)
    return data if isinstance(data, dict) else {}


def _traffic_bucket(node: Any) -> tuple[float | None, int | None]:
    """Extract (availableGb, availableBytes) from a balance bucket."""
    if not isinstance(node, dict):
        return None, None
    traffic = node.get("traffic") if isinstance(node.get("traffic"), dict) else node
    if not isinstance(traffic, dict):
        return None, None
    gb_raw = traffic.get("availableGb")
    bytes_raw = traffic.get("availableBytes")
    gb = float(gb_raw) if gb_raw is not None and str(gb_raw).strip() != "" else None
    try:
        nbytes = int(bytes_raw) if bytes_raw is not None else None
    except (TypeError, ValueError):
        nbytes = None
    if gb is None and nbytes is not None:
        gb = round(nbytes / (1024**3), 3)
    if nbytes is None and gb is not None:
        nbytes = int(gb * (1024**3))
    return gb, nbytes


def normalize_rotating_balance(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten Floppydata rotating balance into UI-friendly fields."""
    total_gb, total_bytes = _traffic_bucket(raw.get("total"))
    if total_gb is None and total_bytes is None:
        # Legacy / unexpected shapes
        for key in ("total", "bytes", "nonExpiring"):
            val = raw.get(key)
            if isinstance(val, (int, float)):
                total_bytes = int(val)
                total_gb = round(total_bytes / (1024**3), 3)
                break
            gb, nbytes = _traffic_bucket(val)
            if gb is not None or nbytes is not None:
                total_gb, total_bytes = gb, nbytes
                break

    exp = raw.get("expiring") if isinstance(raw.get("expiring"), dict) else {}
    exp_gb, _ = _traffic_bucket(exp)
    expires_at = exp.get("expiresAt") if isinstance(exp, dict) else None
    if not isinstance(expires_at, str):
        expires_at = None
    if exp_gb is not None and exp_gb <= 0:
        exp_gb = None
        expires_at = None

    return {
        "balance_gb": total_gb,
        "balance_bytes": total_bytes,
        "expiring_gb": exp_gb,
        "expiring_at": expires_at,
    }


def account_balances(api_key: str) -> dict[str, Any]:
    data = _request("GET", "/v2/account/balances", api_key=api_key)
    return data if isinstance(data, dict) else {}


def list_locations(api_key: str, *, proxy_type: str) -> Any:
    return _request(
        "GET",
        "/v2/proxy/rotating/locations",
        api_key=api_key,
        params={"type": proxy_type},
    )


def list_subusers(api_key: str) -> Any:
    return _request("GET", "/v2/proxy/rotating/subusers", api_key=api_key)


def build_connection(api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    data = _request(
        "POST",
        "/v2/proxy/rotating/connections",
        api_key=api_key,
        json_body=body,
    )
    if not isinstance(data, dict):
        raise FloppydataError("Неожиданный ответ connections")
    return data


def generate_connections(
    api_key: str,
    *,
    proxy_type: str,
    country: str,
    protocol: str,
    rotation: int,
    count: int,
    city: str | None = None,
    state: str | None = None,
    udp: bool = False,
    subuser_id: int | None = None,
) -> list[dict[str, Any]]:
    n = max(1, min(int(count), 20))
    body: dict[str, Any] = {
        "type": proxy_type,
        "country": country.upper(),
        "protocol": protocol,
        "rotation": rotation,
    }
    if state:
        body["state"] = state
    elif city:
        body["city"] = city
    if udp and protocol == "socks5" and proxy_type in ("residential", "mobile"):
        body["udp"] = True
    if subuser_id is not None:
        body["subuserId"] = int(subuser_id)

    items: list[dict[str, Any]] = []
    for _ in range(n):
        raw = build_connection(api_key, body)
        conn = raw.get("connection") if isinstance(raw.get("connection"), dict) else {}
        items.append(
            {
                "connection_string": str(conn.get("connectionString") or ""),
                "protocol": str(conn.get("protocol") or protocol),
                "host": str(conn.get("host") or ""),
                "port": conn.get("port"),
                "username": str(conn.get("username") or ""),
                "password": str(conn.get("password") or ""),
                "parameters": raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {},
            }
        )
    return items
