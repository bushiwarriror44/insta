"""Instagram 2FA backup codes storage and consumption."""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.db import Account

_CODE_SPLIT_RE = re.compile(r"[\s,;]+")


def normalize_backup_code(code: str) -> str:
    return re.sub(r"\s+", "", (code or "").strip()).upper()


def parse_backup_codes_text(raw: str | None) -> list[str]:
    """Parse backup codes from JSON array or whitespace/comma-separated text."""
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return [normalize_backup_code(str(item)) for item in data if str(item).strip()]
    codes = [normalize_backup_code(part) for part in _CODE_SPLIT_RE.split(text)]
    return [code for code in codes if code]


def serialize_backup_codes(codes: list[str]) -> str | None:
    cleaned = [normalize_backup_code(code) for code in codes if normalize_backup_code(code)]
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def backup_codes_for_account(account: Account) -> list[str]:
    return parse_backup_codes_text(account.backup_codes)


def set_backup_codes(account: Account, codes: list[str]) -> None:
    account.backup_codes = serialize_backup_codes(codes)


def consume_next_backup_code(db: Session, account: Account) -> str | None:
    """Pop and persist the next unused backup code for *account*."""
    codes = backup_codes_for_account(account)
    if not codes:
        return None
    code = codes.pop(0)
    account.backup_codes = serialize_backup_codes(codes)
    db.commit()
    db.refresh(account)
    return code


def parse_account_line(line: str) -> dict[str, Any]:
    """Parse ``username:password:backup_codes:url`` account export lines."""
    raw = (line or "").strip()
    if not raw:
        raise ValueError("account line is empty")

    parts = raw.split(":")
    if len(parts) < 2:
        raise ValueError("expected username:password[:backup_codes[:url]]")

    username = parts[0].strip()
    password = parts[1].strip()
    if not username or not password:
        raise ValueError("username and password are required")

    backup_raw = ""
    profile_url = ""
    if len(parts) == 3:
        third = parts[2].strip()
        if third.lower().startswith("http"):
            profile_url = third
        else:
            backup_raw = third
    elif len(parts) >= 4:
        backup_raw = parts[2].strip()
        profile_url = ":".join(parts[3:]).strip()

    backup_codes = parse_backup_codes_text(backup_raw) if backup_raw else []
    return {
        "username": username,
        "password": password,
        "backup_codes": backup_codes,
        "profile_url": profile_url,
    }
