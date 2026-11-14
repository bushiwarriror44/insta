"""Format assistant answers for Telegram."""
from __future__ import annotations

from typing import Any

from app.assistant.chat import Answer
from app.config import Settings, get_settings

ASK_CALLBACK_PREFIX = "tgask:"


def ask_reply_markup(questions: list[str]) -> dict[str, Any] | None:
    """Inline keyboard for assistant clarification questions (max 5)."""
    if not questions:
        return None
    rows: list[list[dict[str, str]]] = []
    for i, raw in enumerate(questions[:5]):
        q = (raw or "").strip()
        if not q:
            continue
        label = q if len(q) <= 48 else q[:45].rstrip() + "…"
        rows.append([{"text": label, "callback_data": f"{ASK_CALLBACK_PREFIX}{i}"}])
    if not rows:
        return None
    return {"inline_keyboard": rows}


def format_answer(answer: Answer, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    lines: list[str] = []
    if answer.reply:
        lines.append(answer.reply.strip())
    if answer.asks:
        lines.append("")
        lines.append("Нужен ответ:")
        for q in answer.asks[:5]:
            lines.append(f"• {q}")
    if answer.used:
        lines.append("")
        lines.append("Инструменты: " + ", ".join(answer.used[:12]))
    if answer.opened and answer.opened.as_url():
        base = (settings.panel_base_url or "").rstrip("/")
        path = answer.opened.as_url()
        if base and path:
            lines.append("")
            lines.append(f"Панель: {base}{path}")
    if not lines:
        lines.append("Готово (пустой ответ).")
    text = "\n".join(lines)
    max_len = settings.telegram_agent_max_message_len
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def format_progress_step(kind: str, text: str, name: str | None = None) -> str:
    label = (name or kind or "шаг").strip()
    body = (text or "").strip()
    if len(body) > 120:
        body = body[:117] + "…"
    return f"{label}: {body}" if body else label
