"""Panel settings store: secret entry path + optional master password hash."""
from __future__ import annotations

import re
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db import PanelSettings

_RESERVED_PREFIXES = ("/api", "/novnc", "/assets", "/llm", "/mcp")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_-]{11,198}$")


def generate_entry_path() -> str:
    return "/" + secrets.token_urlsafe(18).rstrip("=")


def validate_entry_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw.startswith("/"):
        raise ValueError("Путь должен начинаться с /")
    # Collapse trailing slash except root (root not allowed as entry)
    if len(raw) > 1:
        raw = raw.rstrip("/")
    if not _PATH_RE.match(raw):
        raise ValueError(
            "Путь: / + латиница/цифры/_/- , длина сегмента ≥ 11 символов после /"
        )
    lower = raw.lower()
    for prefix in _RESERVED_PREFIXES:
        if lower == prefix or lower.startswith(prefix + "/"):
            raise ValueError(f"Путь не может начинаться с {prefix}")
    return raw


def normalize_request_path(path: str) -> str:
    p = (path or "/").strip() or "/"
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1:
        p = p.rstrip("/")
    return p or "/"


def path_matches_entry(request_path: str, entry_path: str) -> bool:
    req = normalize_request_path(request_path)
    entry = normalize_request_path(entry_path)
    return req == entry or req.startswith(entry + "/")


def generate_llm_gateway_token() -> str:
    return secrets.token_urlsafe(32)


def get_or_create_panel_settings(db: Session) -> PanelSettings:
    row = db.get(PanelSettings, 1)
    if row is not None:
        return row
    row = PanelSettings(
        id=1,
        entry_path=generate_entry_path(),
        master_password_hash=None,
        admin_notes="",
        llm_gateway_token=None,
        llm_gateway_enabled=True,
        floppydata_api_key=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def ensure_llm_gateway_token(db: Session) -> str:
    """Return the gateway API key, creating one on first use."""
    row = get_or_create_panel_settings(db)
    token = (row.llm_gateway_token or "").strip()
    if token:
        return token
    token = generate_llm_gateway_token()
    row.llm_gateway_token = token
    db.commit()
    db.refresh(row)
    return token


def rotate_llm_gateway_token(db: Session) -> str:
    row = get_or_create_panel_settings(db)
    token = generate_llm_gateway_token()
    row.llm_gateway_token = token
    db.commit()
    db.refresh(row)
    return token


def llm_gateway_is_enabled(db: Session) -> bool:
    row = get_or_create_panel_settings(db)
    return bool(getattr(row, "llm_gateway_enabled", True))


def set_llm_gateway_enabled(db: Session, enabled: bool) -> bool:
    row = get_or_create_panel_settings(db)
    row.llm_gateway_enabled = bool(enabled)
    db.commit()
    db.refresh(row)
    return bool(row.llm_gateway_enabled)


def resolve_floppydata_api_key(db: Session) -> str:
    """Env FLOPPYDATA_API_KEY wins; otherwise PanelSettings.floppydata_api_key."""
    env_key = (settings.floppydata_api_key or "").strip()
    if env_key:
        return env_key
    row = get_or_create_panel_settings(db)
    return (getattr(row, "floppydata_api_key", None) or "").strip()


def set_floppydata_api_key(db: Session, api_key: str) -> str:
    row = get_or_create_panel_settings(db)
    cleaned = (api_key or "").strip()
    row.floppydata_api_key = cleaned or None
    db.commit()
    db.refresh(row)
    return (row.floppydata_api_key or "").strip()


def floppydata_key_from_env() -> bool:
    return bool((settings.floppydata_api_key or "").strip())


def auth_is_required(db: Optional[Session] = None) -> bool:
    if settings.admin_token:
        return True
    own = False
    session = db
    if session is None:
        import app.db as db

        session = db.SessionLocal()
        own = True
    try:
        row = session.get(PanelSettings, 1)
        return bool(row and row.master_password_hash)
    finally:
        if own:
            session.close()


def gate_is_enabled(db: Session) -> bool:
    """Secret-path gate runs whenever panel auth is required."""
    return auth_is_required(db)
