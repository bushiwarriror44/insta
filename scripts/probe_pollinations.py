#!/usr/bin/env python3
"""Probe Pollinations video API from worker container (status only, no key in output)."""
from __future__ import annotations

import sys

import httpx

from app.config import settings


def main() -> int:
    url = settings.pollinations_video_url.rstrip("/")
    if not url:
        print("POLLINATIONS_VIDEO_URL empty — pollinations disabled")
        return 1
    headers: dict[str, str] = {}
    if settings.pollinations_api_key:
        headers["Authorization"] = f"Bearer {settings.pollinations_api_key}"
    payload = {"prompt": "probe", "duration": 5, "width": 720, "height": 1280}
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=60)
    except httpx.RequestError as exc:
        print(f"request failed: {exc}")
        return 1
    print(f"status={r.status_code}")
    print((r.text or "")[:300])
    if r.status_code in (401, 403):
        print(
            "hint: fix POLLINATIONS_API_KEY (valid key or remove bad Bearer), "
            "or use FAL_API_KEY / WAN_BASE_URL",
            file=sys.stderr,
        )
        return 1
    if r.status_code >= 400:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
