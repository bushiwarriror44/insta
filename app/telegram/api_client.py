"""Thin Telegram Bot API client (long-poll friendly)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings


class TelegramApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def agent_bot_token(cfg: Settings | None = None) -> str:
    cfg = cfg or get_settings()
    dedicated = (cfg.telegram_agent_bot_token or "").strip()
    if dedicated:
        return dedicated
    return (cfg.telegram_bot_token or "").strip()


def _api_base(token: str) -> str:
    return f"https://api.telegram.org/bot{token}"


def get_updates(
    token: str,
    *,
    offset: int | None = None,
    timeout: int = 50,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    url = f"{_api_base(token)}/getUpdates"
    with httpx.Client(timeout=timeout + 10) as client:
        response = client.get(url, params=params)
        if response.status_code >= 400:
            raise TelegramApiError(response.text[:300], status_code=response.status_code)
        body = response.json()
    if not body.get("ok"):
        raise TelegramApiError(str(body.get("description") or "getUpdates failed"))
    result = body.get("result")
    return result if isinstance(result, list) else []


def send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = True,
    reply_markup: dict[str, Any] | None = None,
) -> int | None:
    url = f"{_api_base(token)}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    with httpx.Client(timeout=30) as client:
        response = client.post(url, json=payload)
        if response.status_code >= 400:
            raise TelegramApiError(response.text[:300], status_code=response.status_code)
        body = response.json()
    if not body.get("ok"):
        raise TelegramApiError(str(body.get("description") or "sendMessage failed"))
    result = body.get("result")
    if isinstance(result, dict) and result.get("message_id") is not None:
        return int(result["message_id"])
    return None


def send_photo(
    token: str,
    chat_id: int,
    photo: bytes | str | Path,
    *,
    caption: str | None = None,
) -> int | None:
    url = f"{_api_base(token)}/sendPhoto"
    data: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1024]
    if isinstance(photo, (bytes, bytearray)):
        files = {"photo": ("shot.png", bytes(photo), "image/png")}
        close_handle = None
    else:
        handle = Path(photo).open("rb")
        close_handle = handle
        files = {"photo": (Path(photo).name, handle, "image/png")}
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(url, data=data, files=files)
            if response.status_code >= 400:
                raise TelegramApiError(response.text[:300], status_code=response.status_code)
            body = response.json()
    finally:
        if close_handle is not None:
            close_handle.close()
    if not body.get("ok"):
        raise TelegramApiError(str(body.get("description") or "sendPhoto failed"))
    result = body.get("result")
    if isinstance(result, dict) and result.get("message_id") is not None:
        return int(result["message_id"])
    return None


def edit_message_text(
    token: str,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    url = f"{_api_base(token)}/editMessageText"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    with httpx.Client(timeout=30) as client:
        response = client.post(url, json=payload)
        if response.status_code >= 400:
            raise TelegramApiError(response.text[:300], status_code=response.status_code)
        body = response.json()
    if not body.get("ok"):
        raise TelegramApiError(str(body.get("description") or "editMessageText failed"))


def answer_callback_query(
    token: str,
    callback_query_id: str,
    *,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    url = f"{_api_base(token)}/answerCallbackQuery"
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    if show_alert:
        payload["show_alert"] = True
    with httpx.Client(timeout=15) as client:
        response = client.post(url, json=payload)
        if response.status_code >= 400:
            raise TelegramApiError(response.text[:300], status_code=response.status_code)
        body = response.json()
    if not body.get("ok"):
        raise TelegramApiError(str(body.get("description") or "answerCallbackQuery failed"))
