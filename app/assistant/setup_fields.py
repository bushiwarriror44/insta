"""Canonical ask_operator field presets for account and proxy setup in the chat UI."""
from __future__ import annotations

from typing import Any

ACCOUNT_FORM_FIELDS: list[dict[str, Any]] = [
    {"id": "proxy_label", "label": "Метка прокси", "kind": "text", "required": True},
    {"id": "username", "label": "Имя пользователя", "kind": "text", "required": True},
    {
        "id": "platform",
        "label": "Площадка",
        "kind": "select",
        "options": ["instagram", "youtube", "tiktok"],
        "required": True,
    },
    {"id": "password", "label": "Пароль Instagram", "kind": "password", "required": False},
    {"id": "email", "label": "Эл. почта", "kind": "text", "required": False},
    {"id": "email_password", "label": "Пароль email", "kind": "password", "required": False},
    {"id": "imap_host", "label": "IMAP хост (если не авто)", "kind": "text", "required": False},
    {"id": "login_identifier", "label": "Логин (email/телефон)", "kind": "text", "required": False},
    {
        "id": "vendor_line",
        "label": "Строка продавца (tab)",
        "kind": "text",
        "required": False,
    },
    {"id": "totp_seed", "label": "Секрет TOTP", "kind": "password", "required": False},
]

PROXY_FORM_FIELDS: list[dict[str, Any]] = [
    {"id": "label", "label": "Метка прокси", "kind": "text", "required": True},
    {
        "id": "url",
        "label": "URL (http://user:pass@host:port)",
        "kind": "password",
        "required": True,
    },
    {"id": "country", "label": "Страна", "kind": "text", "required": False},
]
