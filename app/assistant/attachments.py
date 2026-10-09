"""User image attachments in the assistant chat (library filenames, not bytes)."""
from __future__ import annotations

from typing import Any


def user_content_with_attachments(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "").strip()
    attachments = message.get("attachments") or []
    if not attachments:
        return content
    lines = [content] if content else []
    for att in attachments:
        fn = str(att.get("filename") or "").strip()
        if not fn:
            continue
        mt = str(att.get("media_type") or "image")
        role = str(att.get("role") or "start_image")
        lines.append(f"[вложение: {fn}, {mt}, {role}]")
    return "\n".join(lines)


def messages_for_thread(messages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    talk = [m for m in messages if m.get("role") in ("user", "assistant")]
    out: list[dict[str, str]] = []
    for message in talk[-limit:]:
        if message.get("role") == "user":
            out.append({"role": "user", "content": user_content_with_attachments(message)})
        else:
            out.append({"role": "assistant", "content": str(message.get("content") or "")})
    return out


def attachment_operator_hint(messages: list[dict[str, Any]]) -> str:
    last_user: dict[str, Any] | None = None
    for message in messages:
        if message.get("role") == "user":
            last_user = message
    if last_user is None:
        return ""
    attachments = last_user.get("attachments") or []
    if not attachments:
        return ""
    parts: list[str] = []
    for att in attachments:
        fn = str(att.get("filename") or "").strip()
        if not fn:
            continue
        mt = str(att.get("media_type") or "image")
        role = str(att.get("role") or "start_image")
        parts.append(f"`{fn}` — {mt}, {role}")
    if not parts:
        return ""
    return (
        "Вложения оператора (уже в библиотеке): "
        + "; ".join(parts)
        + ". Для рендера вызови create_render с reference_filename и "
        "input_mode=image_to_video; не выдумывай имя файла."
    )
