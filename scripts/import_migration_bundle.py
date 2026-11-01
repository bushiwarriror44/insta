"""Merge migration bundle into server data/ + SQLite (does not replace whole DB)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.services.migration_bundle import ImportOptions, import_migration_bundle, load_bundle_from_archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Import migration bundle (merge mode).")
    parser.add_argument("archive", type=Path, help="Path to .tar.gz bundle")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prefix", default="qa-", help="Prefix for remapped proxy labels")
    parser.add_argument(
        "--no-skip-existing-accounts",
        action="store_true",
        help="Not implemented for row overwrite; only for future use",
    )
    parser.add_argument(
        "--merge-session-files",
        action="store_true",
        help="For accounts already in DB, copy session files only if missing on disk",
    )
    parser.add_argument(
        "--force-session-files",
        action="store_true",
        help="Overwrite session files on disk (dangerous)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "migration_import_report.json",
        help="Write JSON report (no passwords)",
    )
    args = parser.parse_args()

    if not args.archive.is_file() and not args.archive.is_dir():
        print(f"FAIL\tarchive not found: {args.archive}", file=sys.stderr)
        return 1

    init_db()
    bundle_root, is_temp = load_bundle_from_archive(args.archive)
    temp_parent = bundle_root.parent if is_temp else None

    opts = ImportOptions(
        dry_run=args.dry_run,
        prefix=args.prefix,
        skip_existing_accounts=not args.no_skip_existing_accounts,
        merge_session_files=args.merge_session_files,
        force_session_files=args.force_session_files,
        skip_proxy_overwrite=True,
    )

    db = SessionLocal()
    try:
        report = import_migration_bundle(db, bundle_root, opts)
    finally:
        db.close()
        if is_temp and temp_parent is not None:
            shutil.rmtree(temp_parent, ignore_errors=True)

    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "dry-run" if args.dry_run else "applied"
    print(
        f"OK\t{mode}\tadded_accounts={len(report.accounts_added)}\t"
        f"skipped={len(report.accounts_skipped)}\tfiles_copied={len(report.files_copied)}\t"
        f"errors={len(report.errors)}"
    )
    print(f"Report\t{report_path}")
    if report.errors:
        for err in report.errors[:10]:
            print(f"ERR\t{err}", file=sys.stderr)
        return 1 if not args.dry_run else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
