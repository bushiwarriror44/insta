"""Parse seller export lines: username, password, email, email password."""
from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _split_fields(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("строка продавца пуста")
    if "\t" in text:
        parts = [p.strip() for p in text.split("\t") if p.strip()]
    elif ";" in text:
        parts = [p.strip() for p in text.split(";") if p.strip()]
    else:
        parts = [p for p in re.split(r"\s{2,}|\s+", text) if p.strip()]
    if len(parts) < 4:
        raise ValueError(
            "ожидаются username, password, email, email_password (таб или пробелы)"
        )
    return parts


def looks_like_vendor_line(line: str) -> bool:
    """True when the line is not colon-style account_line but has an email field."""
    raw = (line or "").strip()
    if not raw or ":" in raw:
        return False
    try:
        parts = _split_fields(raw)
    except ValueError:
        return False
    if len(parts) < 3:
        return False
    return "@" in parts[2]


def parse_vendor_line(line: str) -> dict[str, Any]:
    parts = _split_fields(line)
    username, password, email, email_password = parts[0], parts[1], parts[2], parts[3]
    if not username or not password:
        raise ValueError("нужны username и password")
    if not _EMAIL_RE.match(email):
        raise ValueError("третье поле должно быть email-адресом")
    if not email_password:
        raise ValueError("нужен email_password")
    return {
        "username": username,
        "password": password,
        "email": email,
        "email_password": email_password,
    }
