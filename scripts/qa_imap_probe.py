"""Probe IMAP login for Instagram accounts (no passwords in output)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.accounts.email_handler import _resolve_host, imap_configuration_error
from app.db import Account, Platform, SessionLocal, init_db


def _probe_login(email: str, email_password: str, imap_host: str | None) -> tuple[bool, str]:
    config_err = imap_configuration_error(email, imap_host)
    if config_err:
        return False, config_err
    host = _resolve_host(email, (imap_host or "").strip() or None)
    if not host:
        return False, "unknown IMAP host"
    if not (email_password or "").strip():
        return False, "email_password empty"
    try:
        from imap_tools import MailBox  # type: ignore
    except ImportError:
        return False, "imap-tools not installed"
    try:
        with MailBox(host).login(email.strip(), email_password.strip()) as _mbox:
            _mbox.folder.list()
        return True, "ok"
    except Exception as exc:
        msg = str(exc).strip() or type(exc).__name__
        if len(msg) > 200:
            msg = msg[:200] + "…"
        return False, msg


def main() -> int:
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        default = Path.home() / "AppData" / "Local" / "ms-playwright"
        if default.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default)

    init_db()
    db = SessionLocal()
    rows: list[dict] = []
    try:
        accounts = list(
            db.scalars(
                select(Account)
                .where(Account.platform == Platform.instagram)
                .order_by(Account.username)
            ).all()
        )
        seen_emails: set[str] = set()
        for account in accounts:
            email = (account.email or "").strip()
            if not email or email.lower() in seen_emails:
                continue
            seen_emails.add(email.lower())
            ok, detail = _probe_login(
                email,
                account.email_password or "",
                (account.imap_host or "").strip() or None,
            )
            rows.append(
                {
                    "email": email,
                    "username_sample": account.username,
                    "imap_host": _resolve_host(
                        email, (account.imap_host or "").strip() or None
                    ),
                    "ok": ok,
                    "error": None if ok else detail,
                }
            )
            tag = "OK" if ok else "FAIL"
            print(f"{tag}\t{email}\t{detail if not ok else 'login ok'}")
        out_path = ROOT / "data" / "qa_imap_probe.json"
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path} ({len(rows)} unique emails)")
        return 0 if all(r["ok"] for r in rows) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
