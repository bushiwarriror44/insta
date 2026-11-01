"""Instagram first-login / mint batch on host (no secrets in JSON output)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.accounts.connection_test import run_account_connection_test
from app.accounts.first_login_service import run_account_first_login
from app.accounts.mint_mobile_session import mint_mobile_session
from app.db import Account, Platform, Proxy, SessionLocal, init_db


def _imported_filter(db, accounts: list[Account]) -> list[Account]:
    mobile_ids = {
        p.id for p in db.scalars(select(Proxy).where(Proxy.label.like("am-mobile-%")))
    }
    return [a for a in accounts if a.proxy_id in mobile_ids]


def _connection_ok(account: Account, db) -> bool:
    try:
        out = run_account_connection_test(account, db, probe_mobile=False)
        return bool(out.overall_ok)
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imported-only", action="store_true")
    parser.add_argument("--mint-only", action="store_true")
    parser.add_argument("--first-login-only", action="store_true")
    parser.add_argument(
        "--surface",
        choices=("mobile", "desktop"),
        default=None,
        help="login_surface for first-login only",
    )
    parser.add_argument(
        "--set-login-email",
        action="store_true",
        help="set login_identifier to account.email before attempt",
    )
    parser.add_argument("--usernames", nargs="*", help="limit to these usernames")
    parser.add_argument("--pause-sec", type=float, default=3.0)
    args = parser.parse_args()

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        default = Path.home() / "AppData" / "Local" / "ms-playwright"
        if default.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default)

    do_mint = args.mint_only or (not args.mint_only and not args.first_login_only)
    do_first = args.first_login_only or (not args.mint_only and not args.first_login_only)
    if args.mint_only:
        do_first = False
    if args.first_login_only:
        do_mint = False

    init_db()
    db = SessionLocal()
    rows: list[dict] = []
    try:
        q = select(Account).where(Account.platform == Platform.instagram)
        accounts = list(db.scalars(q.order_by(Account.username)).all())
        if args.imported_only:
            accounts = _imported_filter(db, accounts)
        if args.usernames:
            wanted = {u.strip().lstrip("@") for u in args.usernames if u.strip()}
            accounts = [a for a in accounts if a.username in wanted]

        for account in accounts:
            if args.set_login_email and (account.email or "").strip():
                account.login_identifier = (account.email or "").strip()
                db.commit()

            row_base = {
                "username": account.username,
                "email": account.email,
                "login_identifier": account.login_identifier,
            }

            if do_mint:
                try:
                    out = mint_mobile_session(account, db)
                    db.refresh(account)
                    rows.append(
                        {
                            **row_base,
                            "method": "mint_mobile",
                            "ok": out.ok,
                            "challenge": out.challenge,
                            "error": (out.error or "")[:400] or None,
                            "has_session_id": bool((account.session_id or "").strip()),
                            "connection_ok": _connection_ok(account, db),
                        }
                    )
                    tag = "OK" if out.ok else ("CHALLENGE" if out.challenge else "FAIL")
                    print(
                        f"{tag}\tmint\t{account.username}\t{out.error or ''}"[:200]
                    )
                except Exception as exc:
                    db.rollback()
                    rows.append(
                        {
                            **row_base,
                            "method": "mint_mobile",
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}"[:400],
                        }
                    )
                    print(f"ERROR\tmint\t{account.username}\t{exc}"[:200])
                time.sleep(args.pause_sec)

            if do_first:
                try:
                    out = run_account_first_login(
                        account, db, surface=args.surface
                    )
                    db.refresh(account)
                    rows.append(
                        {
                            **row_base,
                            "method": f"first_login_{args.surface or 'default'}",
                            "ok": out.ok,
                            "challenge": out.challenge,
                            "error": (out.error or "")[:400] or None,
                            "has_session_id": bool((account.session_id or "").strip()),
                            "connection_ok": _connection_ok(account, db),
                        }
                    )
                    tag = "OK" if out.ok else ("CHALLENGE" if out.challenge else "FAIL")
                    print(
                        f"{tag}\tfirst-login\t{account.username}\t{out.error or ''}"[:200]
                    )
                except Exception as exc:
                    db.rollback()
                    rows.append(
                        {
                            **row_base,
                            "method": "first_login",
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}"[:400],
                        }
                    )
                    print(f"ERROR\tfirst-login\t{account.username}\t{exc}"[:200])
                time.sleep(args.pause_sec)

        out_path = ROOT / "data" / "qa_ig_first_login_summary.json"
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    rows = existing + rows
            except json.JSONDecodeError:
                pass
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path} ({len(rows)} attempts)")
        ok_count = sum(1 for r in rows if r.get("ok"))
        return 0 if ok_count else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
