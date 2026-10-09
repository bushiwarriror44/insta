"""Operator hints appended to generation error messages."""
from __future__ import annotations

LOCAL_RENDER_HINT_MARKER = "Локальный рендер:"

_LOCAL_SWITCH = (
    "Локальный рендер: в «Администрирование» запустите GPU Salad (Running), "
    "в `.env` задайте `WAN_BASE_URL`, в «Рендеры» выберите бэкенд local "
    "(или `VIDEO_BACKEND=local`)."
)

_LOCAL_CHECK = (
    "Локальный рендер: проверьте `WAN_BASE_URL` в `.env`, Salad Running "
    "(карточка GPU), доступность Wan из контейнера worker."
)


def enrich_generation_error(message: str, *, backend: str | None = None) -> str:
    text = (message or "").strip()
    if LOCAL_RENDER_HINT_MARKER in text:
        return text
    hint = _LOCAL_CHECK if (backend or "").strip().lower() == "local" else _LOCAL_SWITCH
    if not text:
        return hint
    return f"{text} — {hint}"
