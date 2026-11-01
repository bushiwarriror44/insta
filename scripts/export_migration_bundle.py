"""Export accounts, proxies, and session files for server merge (local machine)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Platform, SessionLocal, init_db
from app.services.migration_bundle import export_migration_bundle


def _parse_platforms(raw: str | None) -> set[Platform] | None:
    if not raw or raw.strip().lower() in ("all", "*"):
        return None
    out: set[Platform] = set()
    for part in raw.split(","):
        p = part.strip().lower()
        if not p:
            continue
        out.add(Platform(p))
    return out or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Export migration bundle (secrets inside archive).")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "migration-bundle-export.tar.gz",
        help="Output .tar.gz path",
    )
    parser.add_argument(
        "--platform",
        default="all",
        help="Comma-separated: instagram,youtube,tiktok or all",
    )
    args = parser.parse_args()

    init_db()
    platforms = _parse_platforms(args.platform)
    db = SessionLocal()
    try:
        result = export_migration_bundle(db, args.out, platforms=platforms)
    finally:
        db.close()

    print(
        f"OK\taccounts={result.account_count}\tproxies={result.proxy_count}\t"
        f"files={result.file_count}\t{result.bundle_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
