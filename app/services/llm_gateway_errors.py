"""Human-readable errors for the LLM OpenAI-compatible gateway."""
from __future__ import annotations

import httpx


def explain_llm_upstream_error(exc: BaseException) -> str:
    """Short Russian message for Cursor/clients when upstream Ollama is down."""
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return (
            "Модель не ответила вовремя (таймаут). "
            "Проверьте, что Salad/Ollama запущены."
        )
    if isinstance(exc, httpx.ConnectError):
        return (
            "Не удалось достучаться до модели (AGENT_BASE_URL). "
            "Проверьте GPU/Ollama."
        )
    text = str(exc).strip()
    lower = text.lower()
    if "name or service not known" in lower or "getaddrinfo" in lower or "nodename" in lower:
        return (
            "Не удалось разрешить адрес модели (DNS). "
            "Проверьте AGENT_BASE_URL."
        )
    if "timed out" in lower or "timeout" in lower:
        return (
            "Модель не ответила вовремя (таймаут). "
            "Проверьте, что Salad/Ollama запущены."
        )
    if "connection refused" in lower or "connect call failed" in lower:
        return (
            "Не удалось достучаться до модели (AGENT_BASE_URL). "
            "Проверьте GPU/Ollama."
        )
    if text:
        # Avoid dumping huge exception reprs into clients.
        short = text.replace("\n", " ")[:120]
        return f"Ошибка связи с моделью: {short}"
    return "Ошибка связи с моделью. Проверьте AGENT_BASE_URL и GPU/Ollama."


LLM_BAD_KEY = "Неверный ключ LLM-шлюза. Скопируйте новый из вкладки API."
LLM_MISSING_KEY = "Требуется Authorization Bearer с ключом LLM-шлюза. Скопируйте ключ из вкладки API."
LLM_DISABLED = "LLM-шлюз выключен. Включите его во вкладке API панели."
