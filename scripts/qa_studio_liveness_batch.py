"""Batch Studio liveness probe for imported YouTube/TikTok accounts."""
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

from app.behavior.studio_playwright import probe_studio_session_liveness
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
        mobile_ids = {
            p.id
            for p in db.scalars(select(Proxy).where(Proxy.label.like("am-mobile-%")))
        }
        q = select(Account).where(Account.platform.in_([Platform.youtube, Platform.tiktok]))
        accounts = list(db.scalars(q.order_by(Account.platform, Account.username)).all())
        if args.imported_only:
            accounts = [a for a in accounts if a.proxy_id in mobile_ids]
        for account in accounts:
            platform = account.platform.value
            proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
            if proxy is None:
                rows.append(
                    {
                        "username": account.username,
                        "platform": platform,
                        "ok": False,
                        "error": "no proxy",
                    }
                )
                print(f"FAIL\t{platform}\t{account.username}\tno proxy")
                continue
            live = probe_studio_session_liveness(
                username=account.username,
                proxy_url=proxy.url,
                platform=platform,  # type: ignore[arg-type]
                timezone_id=account.timezone or "UTC",
            )
            rows.append(
                {
                    "username": account.username,
                    "platform": platform,
                    "ok": live.ok,
                    "challenge": live.challenge,
                    "error": (live.error or "")[:400] or None,
                    "page_url": live.page_url,
                }
            )
            tag = "OK" if live.ok else ("CHALLENGE" if live.challenge else "FAIL")
            print(f"{tag}\t{platform}\t{account.username}\t{live.error or ''}"[:200])
        out_path = ROOT / "data" / "qa_studio_liveness_summary.json"
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}")
        return 0 if all(r.get("ok") for r in rows) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
