"""Studio Playwright login for all imported YouTube/TikTok accounts (no secrets in output)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.accounts.studio_login_service import run_studio_login
from app.db import Account, Platform, Proxy, SessionLocal, init_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imported-only", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        default = Path.home() / "AppData" / "Local" / "ms-playwright"
        if default.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default)

    init_db()
    db = SessionLocal()
    rows: list[dict] = []
    try:
        q = select(Account).where(Account.platform.in_([Platform.youtube, Platform.tiktok]))
        accounts = list(db.scalars(q.order_by(Account.platform, Account.username)))
        if args.imported_only:
            mobile_ids = {
                p.id
                for p in db.scalars(select(Proxy).where(Proxy.label.like("am-mobile-%")))
            }
            accounts = [a for a in accounts if a.proxy_id in mobile_ids]
        for account in accounts:
            platform = account.platform.value
            try:
                out = run_studio_login(account, db)
                rows.append({"username": account.username, "platform": platform, "ok": out.ok, "error": out.error})
                tag = "OK" if out.ok else "FAIL"
                print(f"{tag}\t{platform}\t{account.username}\t{out.error or ''}")
            except Exception as exc:
                rows.append(
                    {
                        "username": account.username,
                        "platform": platform,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                    }
                )
                print(f"ERROR\t{platform}\t{account.username}\t{exc}")
        out_path = ROOT / "data" / "qa_studio_login_summary.json"
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}")
        return 0 if all(r.get("ok") for r in rows) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
