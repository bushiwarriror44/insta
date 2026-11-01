"""Optional Studio publish smoke (real network). Default: enqueue only with hold_for_review."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.config import settings
from app.db import Account, Platform, PostJob, Proxy, SessionLocal, init_db
from app.services.review import initial_job_status
from app.services.scheduling import first_legal_slot, placement_problem


def _resolve_video(path: Path | None) -> Path:
    if path is not None and path.is_file():
        return path
    source = settings.video_source_dir
    if not source.exists():
        raise SystemExit(f"no video dir: {source}")
    for ext in ("*.mp4", "*.mov", "*.webm"):
        matches = sorted(source.glob(ext))
        if matches:
            return matches[0]
    raise SystemExit("no video in data/videos/source — pass --video")


def _enqueue(db, account: Account, video: Path, *, hold: bool) -> dict:
    from app.services.scheduling import post_type_for as ptf

    account.hold_for_review = hold
    db.commit()
    scheduled = datetime.now(timezone.utc)
    problem = placement_problem(db, account, scheduled)
    if problem:
        scheduled = first_legal_slot(db, account, scheduled)
    job = PostJob(
        account_id=account.id,
        source_video_path=str(video.resolve()),
        post_type=ptf(account),
        title=video.stem[:100],
        caption_template=video.stem[:100],
        scheduled_for=scheduled,
        status=initial_job_status(account),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {
        "job_id": job.id,
        "status": job.status.value,
        "account": account.username,
        "platform": account.platform.value,
        "hold_for_review": hold,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username-yt", help="YouTube account username")
    parser.add_argument("--username-tt", help="TikTok account username")
    parser.add_argument("--video", type=Path, default=None)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Enqueue jobs (hold_for_review unless --no-hold). Default: dry enqueue only.",
    )
    parser.add_argument(
        "--no-hold",
        action="store_true",
        help="With --execute only: enqueue/run without hold_for_review (dangerous).",
    )
    args = parser.parse_args()
    video = _resolve_video(args.video)
    init_db()
    db = SessionLocal()
    rows: list[dict] = []
    try:
        targets: list[tuple[str, Platform]] = []
        if args.username_yt:
            targets.append((args.username_yt.strip(), Platform.youtube))
        if args.username_tt:
            targets.append((args.username_tt.strip(), Platform.tiktok))
        if not targets:
            targets.append(("ElizabetKnoxrxvsx", Platform.youtube))
            targets.append(("JoelleBuursma9681", Platform.tiktok))

        for uname, platform in targets:
            account = db.scalar(
                select(Account).where(
                    Account.username == uname, Account.platform == platform
                )
            )
            if account is None:
                rows.append({"username": uname, "platform": platform.value, "ok": False, "error": "not found"})
                print(f"FAIL\t{platform.value}\t{uname}\tnot found")
                continue
            if args.execute:
                proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
                if proxy is None:
                    rows.append({"username": uname, "platform": platform.value, "ok": False, "error": "no proxy"})
                    continue
                hold = not args.no_hold
                row = _enqueue(db, account, video, hold=hold)
                if hold:
                    row["note"] = "approve in Activity or POST .../jobs/{id}/approve; start worker to publish"
                    rows.append({**row, "ok": True, "mode": "enqueue_hold"})
                    print(f"OK\tenqueue\t{uname}\tjob {row['job_id']} awaiting_review={row['status']}")
                else:
                    row["note"] = "queued — worker must run"
                    rows.append({**row, "ok": True, "mode": "enqueue"})
                    print(f"OK\tenqueue\t{uname}\tjob {row['job_id']}")
            else:
                row = _enqueue(db, account, video, hold=True)
                row["ok"] = True
                row["mode"] = "enqueue_hold_dry"
                rows.append(row)
                print(f"OK\tdry\t{uname}\tjob {row['job_id']} ({row['status']})")
        out_path = ROOT / "data" / "qa_studio_publish_smoke.json"
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}")
        return 0 if all(r.get("ok") for r in rows) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
