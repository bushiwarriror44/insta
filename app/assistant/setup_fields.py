"""Canonical ask_operator field presets for account, proxy, and publish forms in chat."""

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

PUBLISH_FORM_FIELDS: list[dict[str, Any]] = [
    {"id": "account_id", "label": "Аккаунт", "kind": "select", "required": True},
    {"id": "filename", "label": "Файл из библиотеки", "kind": "select", "required": True},
    {"id": "title", "label": "Заголовок", "kind": "text", "required": False},
    {"id": "caption", "label": "Подпись / caption", "kind": "text", "required": False},
    {"id": "description", "label": "Описание (YouTube)", "kind": "text", "required": False},
    {"id": "tags", "label": "Теги", "kind": "text", "required": False},
    {
        "id": "when",
        "label": "Когда (ISO или пусто = сейчас)",
        "kind": "text",
        "required": False,
    },
    {
        "id": "post_type",
        "label": "Тип поста",
        "kind": "select",
        "options": ["reel", "youtube_short", "tiktok"],
        "required": False,
    },
]

_FORM_KINDS = frozenset({"account", "proxy", "publish"})


def detect_form_kind(
    fields: list[dict[str, Any]] | None,
    explicit: str | None = None,
) -> str | None:
    """Return account|proxy|publish from explicit arg or field ids."""
    raw = (explicit or "").strip().lower()
    if raw in _FORM_KINDS:
        return raw
    ids = {str(field.get("id") or "").strip() for field in fields or [] if isinstance(field, dict)}
    if {"account_id", "filename"} <= ids:
        return "publish"
    if {"proxy_label", "username", "platform"} <= ids:
        return "account"
    if {"label", "url"} <= ids and "username" not in ids and "proxy_label" not in ids:
        return "proxy"
    return None
