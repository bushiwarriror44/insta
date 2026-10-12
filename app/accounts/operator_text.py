"""Wrap common Instagram/Playwright English errors for operators."""
from __future__ import annotations

_WRAPS: tuple[tuple[str, str], ...] = (
    ("feedback required", "Instagram просит замедлиться"),
    ("action blocked", "действие заблокировано"),
    ("challenge required", "нужен challenge"),
    ("please wait a few minutes", "Instagram просит подождать"),
    ("please wait", "Instagram просит подождать"),
    ("timed out", "таймаут"),
    ("timeout", "таймаут"),
)


def operator_error(text: object) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw
    low = raw.lower()
    for needle, ru in _WRAPS:
        if needle not in low:
            continue
        if low == needle or ru in raw:
            return ru if low == needle else raw
        return f"{ru} ({raw})"
    return raw
