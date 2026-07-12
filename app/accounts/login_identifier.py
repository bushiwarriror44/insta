"""Resolve the Instagram login identifier (email, phone, or username)."""
from __future__ import annotations

from typing import Protocol


class _AccountLike(Protocol):
    username: str
    login_identifier: str | None


def resolve_login_identifier(account: _AccountLike) -> str:
    """Return the value to type into Instagram's login form / instagrapi login."""
    explicit = (getattr(account, "login_identifier", None) or "").strip()
    if explicit:
        return explicit
    return (account.username or "").strip()


def is_account_not_found_error(message: str) -> bool:
    lower = (message or "").strip().lower()
    return (
        "can't find an account" in lower
        or "user not found" in lower
        or "doesn't belong to an account" in lower
    )
