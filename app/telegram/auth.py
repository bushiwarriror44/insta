"""Telegram agent authentication via panel admin token."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.panel.settings_store import (
    revoke_telegram_chat,
    telegram_chat_is_allowed,
    telegram_chat_role,
    verify_telegram_auth,
)

WELCOME_UNAUTH = (
    "Панель Reels — агент в Telegram.\n\n"
    "Чтобы давать задания, авторизуйтесь:\n"
    "/auth <ваш ADMIN_TOKEN из .env>\n\n"
    "Токен не пересылайте посторонним. "
    "Рекомендуется отдельный бот (TELEGRAM_AGENT_BOT_TOKEN), не тот же, что алерты."
)

WELCOME_AUTH = (
    "Вы авторизованы. Пишите задание текстом — агент выполнит его и отчитается.\n"
    "Команды: /status /reset /logout /help"
)

HELP_TEXT = (
    "Команды:\n"
    "/auth TOKEN — вход (admin token)\n"
    "/logout — отвязать этот чат\n"
    "/reset — очистить историю диалога\n"
    "/status — состояние\n"
    "/help — эта справка\n\n"
    "Любой другой текст — задание агенту (browser tools включены)."
)


def handle_auth_command(db: Session, chat_id: int, args: str) -> str:
    if not (settings.admin_token or "").strip():
        return "ADMIN_TOKEN не задан на сервере — вход через бот недоступен."
    token = (args or "").strip()
    if not token:
        return "Использование: /auth <токен>"
    if verify_telegram_auth(db, chat_id, token):
        return "Ок, чат привязан. Можете писать задания.\n\n" + WELCOME_AUTH
    return "Неверный токен."


def handle_logout(db: Session, chat_id: int) -> str:
    if revoke_telegram_chat(db, chat_id):
        return "Чат отвязан. Для входа: /auth <token>"
    return "Этот чат не был привязан."


def is_authorized(db: Session, chat_id: int) -> bool:
    return telegram_chat_is_allowed(db, chat_id)


def viewer_role(db: Session, chat_id: int) -> str:
    return telegram_chat_role(db, chat_id) or "owner"
