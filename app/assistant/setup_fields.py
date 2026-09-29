"""Canonical ask_operator field presets for account and proxy setup in the chat UI."""
from __future__ import annotations

from typing import Any

ACCOUNT_FORM_FIELDS: list[dict[str, Any]] = [
    {"id": "proxy_label", "label": "Метка прокси", "kind": "text", "required": True},
    {"id": "username", "label": "Username", "kind": "text", "required": True},
    {
        "id": "platform",
        "label": "Площадка",
        "kind": "select",
        "options": ["instagram", "youtube", "tiktok"],
        "required": True,
    },
    {"id": "password", "label": "Пароль", "kind": "password", "required": True},
    {"id": "totp_seed", "label": "TOTP seed", "kind": "password", "required": False},
    {"id": "email", "label": "Email", "kind": "text", "required": False},
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
