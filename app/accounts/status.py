"""When an operator may mark an account active again."""
from __future__ import annotations

from app.db.models import Account, AccountStatus


class NotResumable(ValueError):
    """Challenge and blocked accounts need a real login, not a status flip."""


_RESUMABLE = {AccountStatus.active, AccountStatus.paused, AccountStatus.cooldown}

_STATUS_RU = {
    "active": "активен",
    "paused": "пауза",
    "challenge": "челлендж",
    "blocked": "заблокирован",
    "cooldown": "пауза IG",
    "awaiting_review": "на проверке",
}


def status_label(value: str) -> str:
    return _STATUS_RU.get(value, value)


def apply_resume(account: Account) -> None:
    if account.status not in _RESUMABLE:
        raise NotResumable(
            f"аккаунт в состоянии «{account.status.value}» нельзя просто возобновить"
        )
    account.cooldown_until = None
    account.status = AccountStatus.active
