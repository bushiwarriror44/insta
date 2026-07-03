from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db import Account


@dataclass(frozen=True)
class RiskProfile:
    name: str
    max_daily_cap: int
    min_gap_hours: float
    off_day_prob_multiplier: float
    warmup_action_cap: int


RISK_PROFILES: dict[str, RiskProfile] = {
    "new": RiskProfile(
        name="new",
        max_daily_cap=2,
        min_gap_hours=6.0,
        off_day_prob_multiplier=1.8,
        warmup_action_cap=5,
    ),
    "warm": RiskProfile(
        name="warm",
        max_daily_cap=4,
        min_gap_hours=4.0,
        off_day_prob_multiplier=1.0,
        warmup_action_cap=8,
    ),
    "risky": RiskProfile(
        name="risky",
        max_daily_cap=1,
        min_gap_hours=8.0,
        off_day_prob_multiplier=2.4,
        warmup_action_cap=3,
    ),
}


def classify_account_risk(account: Account, *, now: datetime | None = None) -> RiskProfile:
    now = now or datetime.now(timezone.utc)
    created = account.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = ((now - created).days if created else 365)

    if account.status.value in {"challenge", "cooldown"}:
        return RISK_PROFILES["risky"]
    if age_days < 30:
        return RISK_PROFILES["new"]
    return RISK_PROFILES["warm"]


def profile_cap_for_account(account: Account) -> int:
    profile = classify_account_risk(account)
    return max(1, min(account.daily_post_cap, profile.max_daily_cap))


def profile_min_gap_for_account(account: Account) -> float:
    profile = classify_account_risk(account)
    return max(account.min_gap_hours, profile.min_gap_hours)


def quarantine_retry_delay(account: Account, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    profile = classify_account_risk(account, now=now)
    if profile.name == "risky":
        return now + timedelta(hours=24)
    if profile.name == "new":
        return now + timedelta(hours=12)
    return now + timedelta(hours=8)
