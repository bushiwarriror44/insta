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

from app.accounts.studio_login_service import list_studio_accounts, run_studio_login_batch
from app.db import SessionLocal, init_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imported-only", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Удалить cookies Studio перед входом (email/пароль из БД)",
    )
    parser.add_argument("--username", default=None, help="Только один аккаунт")
    args = parser.parse_args()
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        default = Path.home() / "AppData" / "Local" / "ms-playwright"
        if default.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default)

    init_db()
    db = SessionLocal()
    try:
        accounts = list_studio_accounts(
            db,
            imported_only=args.imported_only,
            username=args.username,
        )
        if not accounts:
            print("Нет аккаунтов YouTube/TikTok по фильтру")
            return 1

        def on_status(title: str, detail: str | None) -> None:
            if detail:
                print(f"  {title}: {detail}", flush=True)
            else:
                print(f"  {title}", flush=True)

        rows: list[dict] = []
        for account in accounts:
            platform = account.platform.value
            print(f"\n=== {platform}\t{account.username} ===", flush=True)
            batch_rows = run_studio_login_batch(
                db,
                [account],
                force=args.force,
                allow_vnc_fallback=False,
                on_status=on_status,
            )
            rows.extend(batch_rows)
            row = batch_rows[0]
            tag = "OK" if row.get("ok") else "FAIL"
            print(f"{tag}\t{platform}\t{account.username}\t{row.get('error') or ''}", flush=True)

        out_path = ROOT / "data" / "qa_studio_login_summary.json"
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}")
        ok_count = sum(1 for r in rows if r.get("ok"))
        print(f"Итого: {ok_count}/{len(rows)} OK")
        return 0 if ok_count == len(rows) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
