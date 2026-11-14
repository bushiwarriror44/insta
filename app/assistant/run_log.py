"""Per-run log of panel actions and browser clicks."""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

_job_id: ContextVar[int | None] = ContextVar("agent_run_job", default=None)

_SECRET_KEYS = {
    "password",
    "email_password",
    "token",
    "secret",
    "session",
    "sessionid",
    "session_id",
    "proxy_url",
    "totp",
    "totp_seed",
    "backup_codes",
    "authorization",
    "cookie",
    "cookies",
}
_INTERVENTION = re.compile(
    r"капча|captcha|checkpoint|код подтверждения|confirmation code|двухфактор|\b2fa\b|two-factor",
    re.IGNORECASE,
)


def current_job_id() -> int | None:
    return _job_id.get()


@contextmanager
def bind(job_id: int) -> Iterator[None]:
    token = _job_id.set(job_id)
    try:
        yield
    finally:
        _job_id.reset(token)


def _secret_key(key: str) -> bool:
    folded = key.lower().replace("-", "_")
    return folded in _SECRET_KEYS or folded.endswith("_password") or folded.endswith("_token")


def redact(value: Any, key: str = "") -> Any:
    if _secret_key(key):
        return "***"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value[:8]]
    text = str(value).replace("\n", " ").strip()
    if len(text) > 160:
        text = text[:160] + "…"
    return text


def _brief_args(args: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in list(args.items())[:6]:
        shown = redact(value, str(key))
        if isinstance(shown, (dict, list)):
            shown = "…"
        parts.append(f"{key}={shown}")
    return ", ".join(parts)


def summarize(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("ошибка"):
            return "ошибка: " + str(redact(result.get("ошибка")))[:300]
        if result.get("awaiting_code"):
            return "ждёт код входа"
        if result.get("ask"):
            return "нужны данные оператора"
        return "готово"
    return "готово"


def log_tool(phrase: str, args: dict[str, Any] | None, result: Any) -> None:
    head = (phrase or "действие").strip()
    extra = _brief_args(args or {})
    if extra:
        head = f"{head} ({extra})"
    append("tool", f"{head} → {summarize(result)}")


def intervention_text(result: Any) -> str | None:
    """A situation the operator has to resolve by hand. Formal questions use ask_operator."""
    if not isinstance(result, dict) or result.get("ask"):
        return None
    if result.get("awaiting_code"):
        return "Нужен код входа. Введите его в чат."
    blob = " ".join(
        str(result.get(key) or "")
        for key in ("ошибка", "error", "hint", "reason", "message", "status")
    )
    if _INTERVENTION.search(blob):
        text = " ".join(blob.split())
        return text[:500] or "Агенту нужно ваше действие."
    return None


def append(kind: str, text: str) -> None:
    append_for(_job_id.get(), kind, text)


def append_for(job_id: int | None, kind: str, text: str) -> None:
    line = " ".join((text or "").split())
    if job_id is None or not line:
        return
    from app.db.models import AgentRunLog, AssistantJob
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        if db.get(AssistantJob, job_id) is None:
            return
        db.add(
            AgentRunLog(
                assistant_job_id=job_id,
                kind=(kind or "tool")[:16],
                text=line[:2000],
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def format_logs(rows: list[Any]) -> str:
    lines: list[str] = []
    labels = {"tool": "действие", "browser": "браузер", "need": "нужен человек"}
    for row in rows:
        stamp = row.created_at.strftime("%Y-%m-%d %H:%M:%S")
        label = labels.get(row.kind, row.kind)
        lines.append(f"{stamp}  {label}  {row.text}")
    return "\n".join(lines)
