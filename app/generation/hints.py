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

_WAN_TIMEOUT = (
    "процесс Wan на GPU не уложился в 30 минут. "
    "Панель запустит следующую попытку, если они ещё есть."
)

_GPU_BUSY = (
    "GPU уже рендерит другой ролик. Дождитесь его или Stop/Start группы Salad. "
    "Для async нужен новый образ salad-gpu."
)


def _gpu_busy(text: str) -> bool:
    low = text.lower()
    return "409" in text or "gpu already rendering" in low or "занят" in low


def enrich_generation_error(message: str, *, backend: str | None = None) -> str:
    text = (message or "").strip()
    if "524" in text:
        if "шлюз Salad" in text:
            return text
        if not text:
            return _SALAD_GATEWAY
        return f"{text} — {_SALAD_GATEWAY}"
    if _gpu_busy(text):
        if "salad-gpu" in text or "Stop/Start" in text:
            return text
        if not text:
            return _GPU_BUSY
        return f"{text} — {_GPU_BUSY}"
    if "wan timed out" in text.lower():
        if _WAN_TIMEOUT in text:
            return text
        return f"{text} — {_WAN_TIMEOUT}"
    if LOCAL_RENDER_HINT_MARKER in text:
        return text
    # Wan already explained itself (missing package, CUDA, flash-attn). The generic URL hint hides that.
    if (
        "ModuleNotFoundError" in text
        or "Traceback" in text
        or "AssertionError" in text
        or "FLASH_ATTN" in text
        or "flash_attn" in text
        or "attention.py" in text
    ):
        return text
    hint = _LOCAL_CHECK if (backend or "").strip().lower() == "local" else _LOCAL_SWITCH
    if not text:
        return hint
    return f"{text} — {hint}"
