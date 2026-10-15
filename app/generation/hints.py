"""Подсказки оператору, дописываемые к ошибкам генерации."""
from __future__ import annotations

LOCAL_RENDER_HINT_MARKER = "Локальный рендер:"

_LOCAL_SWITCH = (
    "Локальный рендер: в «Администрирование» запустите GPU Salad "
    "(статус «Работает»), в `.env` задайте `WAN_BASE_URL`, в «Рендеры» "
    "выберите бэкенд local (или `VIDEO_BACKEND=local`)."
)

_LOCAL_CHECK = (
    "Локальный рендер: проверьте `WAN_BASE_URL` в `.env`, что Salad "
    "в статусе «Работает» (карточка GPU), и доступность Wan из контейнера worker."
)

_SALAD_GATEWAY = (
    "шлюз Salad оборвал ответ примерно через 100 с. "
    "Длинный Wan идёт короткими запросами: обновите образ salad-gpu и reels-worker."
)


def enrich_generation_error(message: str, *, backend: str | None = None) -> str:
    text = (message or "").strip()
    if "524" in text:
        if "шлюз Salad" in text:
            return text
        if not text:
            return _SALAD_GATEWAY
        return f"{text} — {_SALAD_GATEWAY}"
    if LOCAL_RENDER_HINT_MARKER in text:
        return text
    # Wan already explained itself (missing package, CUDA). The generic URL hint hides that.
    if "ModuleNotFoundError" in text or "Traceback" in text:
        return text
    hint = _LOCAL_CHECK if (backend or "").strip().lower() == "local" else _LOCAL_SWITCH
    if not text:
        return hint
    return f"{text} — {hint}"
