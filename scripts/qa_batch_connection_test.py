"""Run connection_test for every account in DB; print summary (no secrets)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.accounts.connection_test import run_account_connection_test
from app.db import Account, Proxy, SessionLocal, init_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--imported-only",
        action="store_true",
        help="Only accounts on am-mobile-* proxies from accounts/ import",
    )
    args = parser.parse_args()
    init_db()
    db = SessionLocal()
    try:
        accounts = list(db.scalars(select(Account).order_by(Account.platform, Account.username)))
        if args.imported_only:
            mobile_ids = {
                p.id
                for p in db.scalars(select(Proxy).where(Proxy.label.like("am-mobile-%")))
            }
            accounts = [a for a in accounts if a.proxy_id in mobile_ids]
        rows: list[dict] = []
        for account in accounts:
            platform = getattr(account.platform, "value", account.platform)
            try:
                out = run_account_connection_test(account, db, probe_mobile=False)
                ph = out.proxy_health
                ss = out.session_storage
                ia = out.instagram_auth
                session_ok = ss.has_session_id or ss.session_file_exists or ss.session_source == "playwright"
                rows.append(
                    {
                        "username": out.username,
                        "platform": platform,
                        "overall_ok": out.overall_ok,
                        "proxy_label": out.proxy_label,
                        "proxy_ok": ph.ok,
                        "geo_mismatch": ph.geo_mismatch,
                        "session_source": ss.session_source,
                        "has_session": session_ok,
                        "instagram_auth_ok": ia.ok if ia else None,
                    }
                )
                status = "OK" if out.overall_ok else ("WARN" if ph.ok and ph.geo_mismatch else "FAIL")
                print(
                    f"{status}\t{platform}\t{out.username}\tproxy={out.proxy_label}\tsession={ss.session_source}"
                )
            except Exception as exc:
                rows.append(
                    {
                        "username": account.username,
                        "platform": platform,
                        "error": type(exc).__name__,
                        "detail": str(exc)[:200],
                    }
                )
                print(f"ERROR\t{platform}\t{account.username}\t{exc}")
        out_path = ROOT / "data" / "qa_connection_test_summary.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path} ({len(rows)} accounts)")
        failed = sum(1 for r in rows if r.get("overall_ok") is False or "error" in r)
        return 1 if failed else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
