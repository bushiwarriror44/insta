"""Qubax async video generation API client."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.config import Settings, get_settings, settings
from app.services.http import client as http_client
from app.services.media_links import relative_url

QUBAX_TIMEOUT = 60.0
MODELS_CACHE_TTL_S = 600.0
MARKET_CACHE_TTL_S = 60.0

QUBAX_DOCS_URL = "https://qubax.ai/docs"

CURATED_PRESETS: list[dict[str, str]] = [
    {"id": "kling-v3-standard-text-to-video", "label": "Kling V3 Standard (T2V)"},
    {"id": "kling-2-6-pro-text-to-video", "label": "Kling 2.6 Pro (T2V)"},
    {"id": "seedance-2-fast-t2v", "label": "Seedance 2.0 Fast (T2V)"},
    {"id": "video-gen", "label": "Video Gen (T2V, legacy)"},
    {"id": "uncensored-t2v-standard", "label": "Uncensored T2V Standard"},
    {"id": "uncensored-i2v-pro", "label": "Uncensored I2V Pro"},
    {"id": "kling-v3-pro-image-to-video", "label": "Kling V3 Pro (I2V)"},
    {"id": "wan-2-7-image-to-video", "label": "Wan 2.7 (I2V)"},
    {"id": "seedance-2-0-image-to-video", "label": "Seedance 2.0 (I2V)"},
]

TERMINAL_STATUSES = frozenset({"completed", "failed", "error", "cancelled"})


def is_terminal_status(status: str | None) -> bool:
    return str(status or "").lower() in TERMINAL_STATUSES


def extract_video_url(body: dict[str, Any]) -> str | None:
    if not body:
        return None
    direct = body.get("video_url") or body.get("url")
    if direct:
        return str(direct)
    for key in ("output", "result", "data"):
        nested = body.get(key)
        if isinstance(nested, dict):
            url = nested.get("video_url") or nested.get("url")
            if url:
                return str(url)
    return None


_VIDEO_ID_HINTS = (
    "video",
    "t2v",
    "i2v",
    "text-to-video",
    "image-to-video",
    "kling",
    "seedance",
    "wan-",
    "veo",
    "pixverse",
    "longcat",
    "grok-imagine",
)


class QubaxError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


_models_cache: tuple[float, list[dict[str, Any]]] | None = None
_market_list_cache: tuple[float, list[dict[str, Any]]] | None = None
_market_model_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def api_root(cfg: Settings | None = None) -> str:
    cfg = cfg or get_settings()
    base = (cfg.qubax_base_url or "https://api.qubax.ai/v1").rstrip("/")
    return base


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _explain_http(exc: BaseException) -> str:
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):
        return "Qubax не ответил вовремя (таймаут)."
    if isinstance(exc, httpx.ConnectError):
        return "Не удалось достучаться до Qubax API."
    text = str(exc).replace("\n", " ")[:200]
    return f"Ошибка Qubax: {text}" if text else "Ошибка Qubax."


def _raise_http(response: httpx.Response, *, context: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 402:
        raise QubaxError(
            "Недостаточно средств на балансе Qubax (402). Пополните баланс на qubax.ai.",
            status_code=402,
        )
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(
                body.get("error")
                or body.get("message")
                or body.get("detail")
                or ""
            ).strip()
    except (json.JSONDecodeError, ValueError):
        detail = (response.text or "")[:240].strip()
    msg = detail or f"HTTP {response.status_code} ({context})"
    raise QubaxError(msg, status_code=response.status_code)


def filter_video_models(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for preset in CURATED_PRESETS:
        pid = preset["id"]
        if pid not in seen:
            seen.add(pid)
            out.append({"id": pid, "owned_by": "preset", "label": preset["label"]})
    for row in rows:
        mid = str(row.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        lower = mid.lower()
        if not any(hint in lower for hint in _VIDEO_ID_HINTS):
            continue
        seen.add(mid)
        out.append(
            {
                "id": mid,
                "owned_by": str(row.get("owned_by") or ""),
                "object": row.get("object"),
            }
        )
    return out


def list_models(api_key: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    global _models_cache
    now = time.monotonic()
    if not refresh and _models_cache is not None:
        cached_at, data = _models_cache
        if now - cached_at < MODELS_CACHE_TTL_S:
            return data
    root = api_root()
    with http_client(settings, timeout=QUBAX_TIMEOUT, headers=_headers(api_key)) as client:
        response = client.get(f"{root}/models")
        _raise_http(response, context="models")
        body = response.json()
    rows = body.get("data") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        rows = []
    parsed: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, dict) and item.get("id"):
            parsed.append(item)
    data = filter_video_models(parsed)
    _models_cache = (now, data)
    return data


def model_detail(api_key: str, model_id: str) -> dict[str, Any]:
    root = api_root()
    safe = model_id.strip()
    with http_client(settings, timeout=QUBAX_TIMEOUT, headers=_headers(api_key)) as client:
        response = client.get(f"{root}/models/{safe}")
        if response.status_code == 404:
            return {"id": safe}
        _raise_http(response, context="model")
        body = response.json()
    return body if isinstance(body, dict) else {"id": safe}


def billing_balance(api_key: str) -> float | None:
    root = api_root()
    with http_client(settings, timeout=QUBAX_TIMEOUT, headers=_headers(api_key)) as client:
        response = client.get(f"{root}/billing/balance")
        _raise_http(response, context="balance")
        body = response.json()
    if not isinstance(body, dict):
        return None
    if body.get("balance_usd") is not None:
        try:
            return float(body["balance_usd"])
        except (TypeError, ValueError):
            pass
    micros = body.get("balance_micros")
    if micros is not None:
        try:
            return float(micros) / 1_000_000
        except (TypeError, ValueError):
            pass
    for key in ("balance", "balanceUsd", "usd", "amount"):
        raw = body.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def duration_token(seconds: int | float) -> str:
    sec = max(1, int(round(seconds)))
    return f"{sec}s"


def parse_duration_seconds(duration: str | None) -> int:
    raw = (duration or "5s").strip().lower()
    if raw.endswith("s"):
        raw = raw[:-1]
    try:
        return max(1, int(round(float(raw))))
    except (TypeError, ValueError):
        return 5


def estimate_video_cost(
    *,
    price: float | None,
    unit: str | None,
    duration: str | None,
) -> float | None:
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    u = (unit or "job").strip().lower()
    if u in ("job", "request", "generation"):
        return p
    if u == "second":
        return p * parse_duration_seconds(duration)
    return p


def _market_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "name": item.get("name"),
        "price": item.get("price"),
        "unit": item.get("unit"),
        "benchmark": item.get("benchmark"),
        "discount_pct": item.get("discount_pct"),
    }


def market_models_list(*, refresh: bool = False) -> list[dict[str, Any]]:
    global _market_list_cache
    now = time.monotonic()
    if not refresh and _market_list_cache is not None:
        cached_at, data = _market_list_cache
        if now - cached_at < MARKET_CACHE_TTL_S:
            return data
    root = api_root()
    with http_client(settings, timeout=QUBAX_TIMEOUT) as client:
        response = client.get(f"{root}/market/models")
        if response.status_code >= 400:
            return []
        body = response.json()
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        rows = []
    parsed = [_market_row(r) for r in rows if isinstance(r, dict) and r.get("id")]
    by_id = {str(r["id"]): r for r in parsed}
    video_rows: list[dict[str, Any]] = []
    for preset in CURATED_PRESETS:
        pid = preset["id"]
        row = by_id.get(pid, {"id": pid, "price": None, "unit": None})
        if row.get("id") == pid:
            video_rows.append(row)
    for item in parsed:
        mid = str(item.get("id") or "")
        lower = mid.lower()
        if any(hint in lower for hint in _VIDEO_ID_HINTS):
            if mid not in {r["id"] for r in video_rows}:
                video_rows.append(item)
    _market_list_cache = (now, video_rows)
    return video_rows


def market_model(model_id: str, *, refresh: bool = False) -> dict[str, Any]:
    safe = model_id.strip()
    if not safe:
        return {"id": model_id}
    now = time.monotonic()
    cached = _market_model_cache.get(safe)
    if not refresh and cached is not None:
        cached_at, data = cached
        if now - cached_at < MARKET_CACHE_TTL_S:
            return data
    root = api_root()
    with http_client(settings, timeout=QUBAX_TIMEOUT) as client:
        response = client.get(f"{root}/market/models/{safe}")
        if response.status_code == 404:
            data = {"id": safe, "price": None, "unit": None}
        elif response.status_code >= 400:
            data = {"id": safe, "price": None, "unit": None}
        else:
            body = response.json()
            data = _market_row(body) if isinstance(body, dict) else {"id": safe}
    _market_model_cache[safe] = (now, data)
    return data


def market_prices_map(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    return {str(r["id"]): r for r in market_models_list(refresh=refresh) if r.get("id")}


def estimate_jobs(
    lines: list[tuple[str, str | None]],
) -> tuple[list[dict[str, Any]], float | None, int]:
    """lines: (model_id, duration). Returns (items, total_usd, jobs_count)."""
    out: list[dict[str, Any]] = []
    jobs = 0
    known_total = 0.0
    all_known = True
    any_known = False
    for model_id, duration in lines:
        jobs += 1
        mkt = market_model(model_id)
        unit = mkt.get("unit")
        if unit is None:
            unit = "job"
        unit_price = mkt.get("price")
        if unit_price is not None:
            try:
                unit_price = float(unit_price)
            except (TypeError, ValueError):
                unit_price = None
        line_cost = estimate_video_cost(price=unit_price, unit=str(unit or ""), duration=duration)
        if line_cost is None:
            all_known = False
        else:
            known_total += line_cost
            any_known = True
        out.append(
            {
                "model": model_id,
                "unit": unit if isinstance(unit, str) else str(unit) if unit is not None else None,
                "unit_price": unit_price,
                "line_cost": line_cost,
                "duration": duration,
            }
        )
    if all_known and jobs:
        total_usd: float | None = known_total
    elif any_known:
        total_usd = known_total
    else:
        total_usd = None
    return out, total_usd, jobs


def create_video(
    api_key: str,
    *,
    model: str,
    prompt: str,
    duration: str | None = None,
    aspect_ratio: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    root = api_root()
    payload: dict[str, Any] = {"model": model.strip(), "prompt": prompt.strip()}
    if duration:
        payload["duration"] = duration
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if image_url:
        payload["image_url"] = image_url
    with http_client(settings, timeout=QUBAX_TIMEOUT, headers=_headers(api_key)) as client:
        response = client.post(f"{root}/video/generations", json=payload)
        _raise_http(response, context="submit")
        body = response.json()
    if not isinstance(body, dict):
        raise QubaxError("Qubax вернул пустой ответ на submit")
    job_id = body.get("id")
    if job_id is None or job_id == "":
        raise QubaxError("Qubax не вернул id задачи")
    body["id"] = str(job_id)
    return body


def get_video_job(api_key: str, external_id: str) -> dict[str, Any]:
    root = api_root()
    safe = external_id.strip()
    with http_client(settings, timeout=QUBAX_TIMEOUT, headers=_headers(api_key)) as client:
        response = client.get(f"{root}/video/generations/{safe}")
        _raise_http(response, context="status")
        body = response.json()
    if not isinstance(body, dict):
        raise QubaxError("Qubax вернул некорректный статус")
    return body


def poll_video_job(
    api_key: str,
    external_id: str,
    *,
    timeout_s: float | None = None,
    poll_s: float | None = None,
) -> dict[str, Any]:
    cfg = get_settings()
    deadline = time.monotonic() + (timeout_s if timeout_s is not None else cfg.generation_timeout_seconds)
    interval = poll_s if poll_s is not None else cfg.generation_poll_seconds
    while True:
        body = get_video_job(api_key, external_id)
        status = str(body.get("status") or "").lower()
        if is_terminal_status(status):
            return body
        if time.monotonic() > deadline:
            raise QubaxError(
                f"Qubax не завершил {external_id} за {cfg.generation_timeout_seconds:.0f}с",
                status_code=504,
            )
        time.sleep(interval)


def public_reference_url(
    filename: str,
    cfg: Settings | None = None,
    *,
    public_base: str | None = None,
) -> str:
    cfg = cfg or get_settings()
    base = (public_base or cfg.api_public_base_url or "").strip().rstrip("/")
    if not base:
        raise QubaxError(
            "Для image-to-video укажите публичный URL API в настройках Qubax "
            "или задайте API_PUBLIC_BASE_URL.",
            status_code=400,
        )
    rel = relative_url(filename, prefix="/api/qubax/refs", settings=cfg)
    return f"{base}{rel}"


def resolve_image_filename_for_job(image_filename: str | None) -> str:
    from pathlib import Path

    from app.api.routes.videos import IMAGE_EXTENSIONS, _named_file
    from app.config import get_settings

    cfg = get_settings()
    name = (image_filename or "").strip()
    if not name:
        raise QubaxError("Для I2V укажите image_filename", status_code=400)
    path = _named_file(cfg.video_source_dir, name)
    if path is None:
        path = _named_file(cfg.media_dir, name)
    if path is None:
        raise QubaxError("Файл референса не найден в библиотеке", status_code=400)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise QubaxError("I2V: нужен файл изображения", status_code=400)
    return Path(name).name
