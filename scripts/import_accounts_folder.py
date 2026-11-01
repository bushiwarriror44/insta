"""One-off import from ./accounts/*.txt into SQLite (run inside repo or Docker).

Does not print passwords. Labels proxies am-mobile-01.. from proxies.txt.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_DIR = ROOT / "accounts"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.accounts.device_factory import patch_device_app_profile_file
from app.accounts.session_manager import ensure_fingerprint_and_proxy
from app.accounts.vendor_line import parse_vendor_line
from app.config import settings
from app.db import Account, Platform, Proxy, SessionLocal, init_db
from app.db.models import AccountStatus
from app.geo.timezone_normalize import is_placeholder_timezone, timezone_from_proxy
from app.proxies.pool import health_check_record, upsert_proxy

_COUNTRY_RE = re.compile(r"country-([a-z]{2})", re.I)


def _country_from_proxy_url(url: str) -> str | None:
    m = _COUNTRY_RE.search(url)
    return m.group(1).upper() if m else None


def import_proxies(db) -> list[str]:
    path = ACCOUNTS_DIR / "proxies.txt"
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    labels: list[str] = []
    for i, url in enumerate(lines, start=1):
        label = f"am-mobile-{i:02d}"
        country = _country_from_proxy_url(url) or "AM"
        upsert_proxy(db, label=label, url=url, country=country, timezone_name=None, notes="import accounts/")
        labels.append(label)
        proxy = db.scalar(select(Proxy).where(Proxy.label == label))
        ok, _, err = health_check_record(db, proxy=proxy)
        status = "ok" if ok else "warn"
        detail = "" if ok else (err or "health fail")[:120]
        print(f"proxy {label} {status} {detail}")
    return labels


def _proxy_label(labels: list[str], index: int) -> str:
    return labels[index % len(labels)]


def import_instagram(db, proxy_labels: list[str]) -> int:
    path = ACCOUNTS_DIR / "inst.txt"
    count = 0
    for i, line in enumerate(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()):
        parsed = parse_vendor_line(line)
        label = _proxy_label(proxy_labels, i)
        proxy = db.scalar(select(Proxy).where(Proxy.label == label))
        assert proxy is not None
        username = parsed["username"]
        existing = db.scalar(
            select(Account).where(Account.username == username, Account.platform == Platform.instagram)
        )
        account = existing or Account(username=username, platform=Platform.instagram)
        if existing is None:
            db.add(account)
        account.password = parsed["password"]
        account.email = parsed["email"]
        account.email_password = parsed["email_password"]
        account.proxy_id = proxy.id
        account.platform = Platform.instagram
        if is_placeholder_timezone(account.timezone or ""):
            account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
        account.status = AccountStatus.active
        db.commit()
        ensure_fingerprint_and_proxy(
            account.username,
            country=proxy.country or "US",
            timezone_id=account.timezone,
        )
        patch_device_app_profile_file(account.username)
        from app.accounts.email_handler import imap_configuration_error

        imap_warn = imap_configuration_error(
            (account.email or "").strip(),
            (account.imap_host or "").strip() or None,
        )
        if imap_warn:
            print(f"  warn IMAP @{username}: {imap_warn[:120]}")
        elif account.email_password and "onet.pl" in (account.email or "").lower():
            print(
                f"  warn @{username}: onet.pl — проверьте email_password "
                "(IMAP: imap.poczta.onet.pl) до автовхода"
            )
        count += 1
        print(f"instagram @{username} -> {label}")
    return count


def import_youtube(db, proxy_labels: list[str]) -> int:
    path = ACCOUNTS_DIR / "google.txt"
    count = 0
    for i, line in enumerate(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()):
        email, password = [p.strip() for p in line.split("|", 1)]
        username = email.split("@", 1)[0][:200]
        label = _proxy_label(proxy_labels, i)
        proxy = db.scalar(select(Proxy).where(Proxy.label == label))
        assert proxy is not None
        existing = db.scalar(
            select(Account).where(Account.username == username, Account.platform == Platform.youtube)
        )
        account = existing or Account(username=username, platform=Platform.youtube)
        if existing is None:
            db.add(account)
        account.password = password
        account.email = email
        account.login_identifier = email
        account.proxy_id = proxy.id
        account.platform = Platform.youtube
        account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
        account.status = AccountStatus.active
        db.commit()
        count += 1
        print(f"youtube @{username} -> {label}")
    return count


def import_tiktok(db, proxy_labels: list[str]) -> int:
    path = ACCOUNTS_DIR / "tiktok.txt"
    count = 0
    for i, line in enumerate(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()):
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 4:
            print(f"tiktok skip line {i + 1}: need 4 fields")
            continue
        email, _mail_pass, _extra, password = parts[0], parts[1], parts[2], parts[3]
        username = email.split("@", 1)[0][:200]
        label = _proxy_label(proxy_labels, i)
        proxy = db.scalar(select(Proxy).where(Proxy.label == label))
        assert proxy is not None
        existing = db.scalar(
            select(Account).where(Account.username == username, Account.platform == Platform.tiktok)
        )
        account = existing or Account(username=username, platform=Platform.tiktok)
        if existing is None:
            db.add(account)
        account.password = password
        account.email = email
        account.login_identifier = email
        account.proxy_id = proxy.id
        account.platform = Platform.tiktok
        account.timezone = timezone_from_proxy(proxy.timezone, proxy.country)
        account.status = AccountStatus.active
        db.commit()
        count += 1
        print(f"tiktok @{username} -> {label}")
    return count


def main() -> None:
    if not ACCOUNTS_DIR.is_dir():
        raise SystemExit(f"нет каталога {ACCOUNTS_DIR}")
    init_db()
    with SessionLocal() as db:
        labels = import_proxies(db)
        ig = import_instagram(db, labels)
        yt = import_youtube(db, labels)
        tt = import_tiktok(db, labels)
    print(f"done proxies={len(labels)} ig={ig} yt={yt} tt={tt} db={settings.database_url}")


if __name__ == "__main__":
    main()
