"""Panel settings store: secret entry path + optional master password hash."""
from __future__ import annotations

import json
import re
import secrets
from typing import Any, Optional

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
        floppydata_last_form=None,
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


def resolve_hero_sms_api_key(db: Session) -> str:
    """Env HERO_SMS_API_KEY wins; otherwise PanelSettings.hero_sms_api_key."""
    env_key = (settings.hero_sms_api_key or "").strip()
    if env_key:
        return env_key
    row = get_or_create_panel_settings(db)
    return (getattr(row, "hero_sms_api_key", None) or "").strip()


def set_hero_sms_api_key(db: Session, api_key: str) -> str:
    row = get_or_create_panel_settings(db)
    cleaned = (api_key or "").strip()
    row.hero_sms_api_key = cleaned or None
    db.commit()
    db.refresh(row)
    return (row.hero_sms_api_key or "").strip()


def hero_sms_key_from_env() -> bool:
    return bool((settings.hero_sms_api_key or "").strip())


def get_hero_sms_last_form(db: Session) -> dict[str, Any] | None:
    row = get_or_create_panel_settings(db)
    raw = getattr(row, "hero_sms_last_form", None)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def resolve_qubax_api_key(db: Session) -> str:
    env_key = (settings.qubax_api_key or "").strip()
    if env_key:
        return env_key
    row = get_or_create_panel_settings(db)
    return (getattr(row, "qubax_api_key", None) or "").strip()


def set_qubax_api_key(db: Session, api_key: str) -> str:
    row = get_or_create_panel_settings(db)
    cleaned = (api_key or "").strip()
    row.qubax_api_key = cleaned or None
    db.commit()
    db.refresh(row)
    return (row.qubax_api_key or "").strip()


def qubax_key_from_env() -> bool:
    return bool((settings.qubax_api_key or "").strip())


def get_qubax_last_form(db: Session) -> dict[str, Any] | None:
    row = get_or_create_panel_settings(db)
    raw = getattr(row, "qubax_last_form", None)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


_QUBAX_FORM_KEYS = (
    "mode",
    "model",
    "prompt",
    "duration",
    "aspect_ratio",
    "image_filename",
    "variant_models",
    "variants",
    "selected_presets",
    "model_tab",
    "api_public_base_url",
    "default_model",
    "default_model_i2v",
)


def set_qubax_last_form(
    db: Session,
    form: dict[str, Any] | None,
    *,
    merge: bool = True,
) -> dict[str, Any] | None:
    row = get_or_create_panel_settings(db)
    if form is None:
        row.qubax_last_form = None
        db.commit()
        db.refresh(row)
        return None
    base = (get_qubax_last_form(db) or {}) if merge else {}
    cleaned: dict[str, Any] = {k: v for k, v in base.items() if k in _QUBAX_FORM_KEYS}
    for key in _QUBAX_FORM_KEYS:
        if key not in form:
            continue
        value = form[key]
        if value is None and key == "image_filename":
            cleaned.pop("image_filename", None)
            continue
        if value is None and key in ("variants", "variant_models", "selected_presets"):
            cleaned[key] = []
            continue
        if value is not None or key in ("image_filename",):
            if value is not None and value != "":
                cleaned[key] = value
            elif key == "image_filename" and form.get("image_filename") == "":
                cleaned.pop("image_filename", None)
    row.qubax_last_form = json.dumps(cleaned, ensure_ascii=False) if cleaned else None
    db.commit()
    db.refresh(row)
    return cleaned or None


def resolve_qubax_api_public_base(db: Session) -> tuple[str, str]:
    """Base URL for signed I2V refs: (url, source: env|panel|salad|none)."""
    env = (settings.api_public_base_url or "").strip().rstrip("/")
    if env:
        return env, "env"
    form = get_qubax_last_form(db) or {}
    panel = str(form.get("api_public_base_url") or "").strip().rstrip("/")
    if panel:
        return panel, "panel"
    salad = (settings.salad_gpu_patch_public_base or "").strip().rstrip("/")
    if salad:
        return salad, "salad"
    return "", "none"


def resolve_qubax_default_model(db: Session, *, i2v: bool = False) -> str:
    if i2v:
        env = (settings.qubax_default_model_i2v or "").strip()
        fallback = "uncensored-i2v-pro"
    else:
        env = (settings.qubax_default_model or "").strip()
        fallback = "kling-v3-standard-text-to-video"
    if env:
        return env
    form = get_qubax_last_form(db) or {}
    key = "default_model_i2v" if i2v else "default_model"
    from_panel = str(form.get(key) or "").strip()
    if from_panel:
        return from_panel
    return fallback


def set_hero_sms_last_form(db: Session, form: dict[str, Any] | None) -> dict[str, Any] | None:
    row = get_or_create_panel_settings(db)
    if not form:
        row.hero_sms_last_form = None
        db.commit()
        db.refresh(row)
        return None
    cleaned: dict[str, Any] = {}
    for key in ("service", "country_id", "operator", "strict_price"):
        if key in form and form[key] is not None:
            cleaned[key] = form[key]
    row.hero_sms_last_form = json.dumps(cleaned, ensure_ascii=False) if cleaned else None
    db.commit()
    db.refresh(row)
    return cleaned or None


def get_floppydata_last_form(db: Session) -> dict[str, Any] | None:
    row = get_or_create_panel_settings(db)
    raw = getattr(row, "floppydata_last_form", None)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def set_floppydata_last_form(db: Session, form: dict[str, Any] | None) -> dict[str, Any] | None:
    row = get_or_create_panel_settings(db)
    if not form:
        row.floppydata_last_form = None
        db.commit()
        db.refresh(row)
        return None
    cleaned: dict[str, Any] = {}
    for key in (
        "type",
        "country",
        "city",
        "state",
        "protocol",
        "rotation",
        "udp",
        "count",
        "subuser_id",
    ):
        if key in form and form[key] is not None:
            cleaned[key] = form[key]
    row.floppydata_last_form = json.dumps(cleaned, ensure_ascii=False) if cleaned else None
    db.commit()
    db.refresh(row)
    return cleaned or None


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
