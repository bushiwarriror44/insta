"""Export/import migration bundles (accounts, proxies, session files) for server merge."""
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.device_factory import device_path, patch_device_app_profile_file
from app.accounts.playwright_session import (
    playwright_state_path,
    playwright_state_write_path,
)
from app.accounts.session_manager import session_path
from app.config import Settings, settings
from app.db import Account, Platform, Proxy
from app.db.models import AccountStatus
from app.proxies.pool import normalize_proxy_url

BUNDLE_VERSION = "v1"
BUNDLE_ROOT = "migration-bundle-v1"
MANIFEST_NAME = "manifest.json"
ENTITIES_NAME = "entities.json"
FILES_DIR = "files"


class MigrationBundleError(RuntimeError):
    pass


def url_fingerprint(url: str) -> str:
    normalized = normalize_proxy_url((url or "").strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _rel_under_data(path: Path, data_dir: Path | None = None) -> str | None:
    root = (data_dir or settings.data_dir).resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def session_file_paths_for_account(account: Account) -> list[Path]:
    """Absolute paths to bundle for this account (existing files only)."""
    username = account.username
    platform = account.platform
    paths: list[Path] = []

    if platform in (Platform.youtube, Platform.tiktok):
        p = playwright_state_write_path(username, platform.value)
        if p.exists():
            paths.append(p)
        legacy = playwright_state_path(username, platform.value)
        if legacy.exists() and legacy not in paths:
            paths.append(legacy)
    elif platform is Platform.instagram:
        pw = playwright_state_path(username, None)
        if pw.exists():
            paths.append(pw)
        dev = device_path(username)
        if dev.exists():
            paths.append(dev)
        sess = session_path(username)
        if sess.exists():
            paths.append(sess)
    return paths


def _account_to_entity(account: Account, proxy_label: str | None) -> dict[str, Any]:
    return {
        "platform": account.platform.value,
        "username": account.username,
        "proxy_label": proxy_label,
        "password": account.password or "",
        "login_identifier": account.login_identifier,
        "email": account.email,
        "email_password": account.email_password,
        "imap_host": account.imap_host,
        "totp_seed": account.totp_seed,
        "backup_codes": account.backup_codes,
        "session_id": account.session_id,
        "login_surface": account.login_surface,
        "status": account.status.value,
        "daily_post_cap": account.daily_post_cap,
        "min_gap_hours": account.min_gap_hours,
        "active_hour_start": account.active_hour_start,
        "active_hour_end": account.active_hour_end,
        "timezone": account.timezone,
        "caption_profile": account.caption_profile,
        "hold_for_review": account.hold_for_review,
        "brief": account.brief or "",
        "notes": account.notes,
    }


def _proxy_to_entity(proxy: Proxy) -> dict[str, Any]:
    return {
        "label": proxy.label,
        "url": proxy.url,
        "country": proxy.country,
        "timezone": proxy.timezone,
        "notes": proxy.notes,
    }


@dataclass
class ExportResult:
    bundle_path: Path
    account_count: int
    proxy_count: int
    file_count: int


def export_migration_bundle(
    db: Session,
    out_path: Path,
    *,
    platforms: set[Platform] | None = None,
    cfg: Settings | None = None,
) -> ExportResult:
    cfg = cfg or settings
    data_dir = cfg.data_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bundle_id = f"migration-{stamp}"

    query = select(Account).order_by(Account.platform, Account.username)
    accounts = list(db.scalars(query).all())
    if platforms is not None:
        accounts = [a for a in accounts if a.platform in platforms]

    proxy_ids: set[int] = set()
    for a in accounts:
        if a.proxy_id is not None:
            proxy_ids.add(a.proxy_id)

    proxies: list[Proxy] = []
    if proxy_ids:
        proxies = list(
            db.scalars(select(Proxy).where(Proxy.id.in_(proxy_ids)).order_by(Proxy.label)).all()
        )

    proxy_by_id = {p.id: p for p in proxies}
    file_entries: list[dict[str, Any]] = []
    account_manifest: list[dict[str, Any]] = []
    entities_accounts: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / BUNDLE_ROOT
        files_root = root / FILES_DIR
        files_root.mkdir(parents=True)

        seen_rel: set[str] = set()
        for account in accounts:
            plabel = None
            if account.proxy_id and account.proxy_id in proxy_by_id:
                plabel = proxy_by_id[account.proxy_id].label
            rel_paths: list[str] = []
            for abs_path in session_file_paths_for_account(account):
                rel = _rel_under_data(abs_path, data_dir)
                if not rel or rel in seen_rel:
                    continue
                seen_rel.add(rel)
                dest = files_root / rel.replace("/", "\\") if False else files_root / Path(rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(abs_path, dest)
                file_entries.append(
                    {
                        "path": rel,
                        "sha256": sha256_file(dest),
                        "bytes": dest.stat().st_size,
                    }
                )
                rel_paths.append(rel)

            account_manifest.append(
                {
                    "platform": account.platform.value,
                    "username": account.username,
                    "proxy_label": plabel,
                    "session_files": rel_paths,
                    "has_session_id": bool((account.session_id or "").strip()),
                    "status": account.status.value,
                }
            )
            entities_accounts.append(_account_to_entity(account, plabel))

        proxy_manifest = [
            {
                "label": p.label,
                "url_fingerprint": url_fingerprint(p.url),
                "country": p.country,
                "timezone": p.timezone,
            }
            for p in proxies
        ]

        manifest = {
            "version": BUNDLE_VERSION,
            "bundle_id": bundle_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_database_url": cfg.database_url.split("?", 1)[0],
            "proxies": proxy_manifest,
            "accounts": account_manifest,
            "files": file_entries,
        }

        entities = {
            "proxies": [_proxy_to_entity(p) for p in proxies],
            "accounts": entities_accounts,
        }

        root.mkdir(parents=True, exist_ok=True)
        (root / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / ENTITIES_NAME).write_text(
            json.dumps(entities, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        out_path = out_path.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        archive = out_path if str(out_path).endswith(".tar.gz") else out_path.with_suffix(".tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(root, arcname=BUNDLE_ROOT)
        out_path = archive

    return ExportResult(
        bundle_path=out_path,
        account_count=len(accounts),
        proxy_count=len(proxies),
        file_count=len(file_entries),
    )


def _tar_extractall(tar: tarfile.TarFile, path: str) -> None:
    try:
        tar.extractall(path, filter="data")
    except TypeError:
        tar.extractall(path)


def extract_bundle(archive_path: Path) -> Path:
    """Return path to BUNDLE_ROOT inside temp or extracted dir."""
    archive_path = archive_path.resolve()
    if archive_path.is_dir():
        inner = archive_path / BUNDLE_ROOT
        if inner.is_dir():
            return inner
        if (archive_path / MANIFEST_NAME).is_file():
            return archive_path
        raise MigrationBundleError(f"not a migration bundle dir: {archive_path}")

    tmp = tempfile.mkdtemp(prefix="migration-import-")
    with tarfile.open(archive_path, "r:*") as tar:
        _tar_extractall(tar, tmp)
    inner = Path(tmp) / BUNDLE_ROOT
    if not inner.is_dir():
        raise MigrationBundleError("archive missing migration-bundle-v1/")
    return inner


@dataclass
class ImportOptions:
    dry_run: bool = False
    prefix: str = "qa-"
    skip_existing_accounts: bool = True
    merge_session_files: bool = False
    force_session_files: bool = False
    skip_proxy_overwrite: bool = True


@dataclass
class ImportReport:
    dry_run: bool
    bundle_id: str
    proxies_added: list[str] = field(default_factory=list)
    proxies_reused: list[str] = field(default_factory=list)
    proxies_remapped: dict[str, str] = field(default_factory=dict)
    accounts_added: list[str] = field(default_factory=list)
    accounts_skipped: list[dict[str, str]] = field(default_factory=list)
    files_copied: list[str] = field(default_factory=list)
    files_skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "bundle_id": self.bundle_id,
            "proxies_added": self.proxies_added,
            "proxies_reused": self.proxies_reused,
            "proxies_remapped": self.proxies_remapped,
            "accounts_added": self.accounts_added,
            "accounts_skipped": self.accounts_skipped,
            "files_copied": self.files_copied,
            "files_skipped": self.files_skipped,
            "errors": self.errors,
        }


def _unique_proxy_label(db: Session, base: str) -> str:
    label = base
    n = 0
    while db.scalar(select(Proxy).where(Proxy.label == label)) is not None:
        n += 1
        label = f"{base}-{n}"
    return label


def _resolve_proxy(
    db: Session,
    entity: dict[str, Any],
    label_map: dict[str, str],
    opts: ImportOptions,
    report: ImportReport,
) -> str | None:
    """Map bundle proxy label to effective label on server; return label or None on error."""
    label = (entity.get("label") or "").strip()
    url = normalize_proxy_url((entity.get("url") or "").strip())
    if not label or not url:
        report.errors.append(f"proxy invalid: label={label!r}")
        return None

    if label in label_map:
        return label_map[label]

    existing = db.scalar(select(Proxy).where(Proxy.label == label))
    if existing is None:
        if opts.dry_run:
            label_map[label] = label
            report.proxies_added.append(label)
            return label
        proxy = Proxy(
            label=label,
            url=url,
            country=entity.get("country"),
            timezone=entity.get("timezone"),
            notes=entity.get("notes"),
        )
        db.add(proxy)
        db.commit()
        db.refresh(proxy)
        label_map[label] = label
        report.proxies_added.append(label)
        return label

    if normalize_proxy_url(existing.url) == url:
        label_map[label] = label
        report.proxies_reused.append(label)
        return label

    if opts.skip_proxy_overwrite:
        new_label = _unique_proxy_label(db, f"{opts.prefix}{label}")
        if opts.dry_run:
            label_map[label] = new_label
            report.proxies_remapped[label] = new_label
            report.proxies_added.append(new_label)
            return new_label
        proxy = Proxy(
            label=new_label,
            url=url,
            country=entity.get("country") or existing.country,
            timezone=entity.get("timezone") or existing.timezone,
            notes=entity.get("notes") or existing.notes,
        )
        db.add(proxy)
        db.commit()
        db.refresh(proxy)
        label_map[label] = new_label
        report.proxies_remapped[label] = new_label
        report.proxies_added.append(new_label)
        return new_label

    report.errors.append(f"proxy label {label} exists with different URL (skip_proxy_overwrite=false not implemented)")
    return None


def _apply_account_entity(
    db: Session,
    entity: dict[str, Any],
    proxy_id: int | None,
) -> Account:
    platform = Platform(entity["platform"])
    account = Account(username=entity["username"], platform=platform)
    db.add(account)
    account.password = entity.get("password") or ""
    account.login_identifier = entity.get("login_identifier")
    account.email = entity.get("email")
    account.email_password = entity.get("email_password")
    account.imap_host = entity.get("imap_host")
    account.totp_seed = entity.get("totp_seed")
    account.backup_codes = entity.get("backup_codes")
    account.session_id = entity.get("session_id")
    account.login_surface = entity.get("login_surface")
    try:
        account.status = AccountStatus(entity.get("status") or AccountStatus.active.value)
    except ValueError:
        account.status = AccountStatus.active
    account.proxy_id = proxy_id
    account.daily_post_cap = int(entity.get("daily_post_cap") or 3)
    account.min_gap_hours = float(entity.get("min_gap_hours") or 4.0)
    account.active_hour_start = int(entity.get("active_hour_start") or 10)
    account.active_hour_end = int(entity.get("active_hour_end") or 23)
    account.timezone = entity.get("timezone") or "UTC"
    account.caption_profile = entity.get("caption_profile")
    account.hold_for_review = bool(entity.get("hold_for_review"))
    account.brief = entity.get("brief") or ""
    account.notes = entity.get("notes")
    db.commit()
    db.refresh(account)
    return account


def _copy_bundle_files(
    bundle_root: Path,
    manifest_files: list[dict[str, Any]],
    rel_paths: list[str],
    *,
    data_dir: Path,
    opts: ImportOptions,
    report: ImportReport,
    account_key: str,
    is_new_account: bool,
) -> None:
    if not is_new_account and not opts.merge_session_files:
        return

    files_root = bundle_root / FILES_DIR
    for rel in rel_paths:
        src = files_root / Path(rel)
        dest = data_dir / rel
        entry = next((f for f in manifest_files if f.get("path") == rel), None)
        if not src.is_file():
            report.files_skipped.append(
                {"path": rel, "reason": "missing in bundle", "account": account_key}
            )
            continue
        if dest.exists() and not opts.force_session_files:
            report.files_skipped.append(
                {
                    "path": rel,
                    "reason": "dest exists",
                    "account": account_key,
                }
            )
            continue
        if opts.dry_run:
            report.files_copied.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        if entry and entry.get("sha256"):
            if sha256_file(dest) != entry["sha256"]:
                report.errors.append(f"sha256 mismatch after copy: {rel}")
        report.files_copied.append(rel)


def import_migration_bundle(
    db: Session,
    bundle_root: Path,
    opts: ImportOptions | None = None,
    *,
    cfg: Settings | None = None,
) -> ImportReport:
    opts = opts or ImportOptions()
    cfg = cfg or settings
    data_dir = cfg.data_dir

    manifest = json.loads((bundle_root / MANIFEST_NAME).read_text(encoding="utf-8"))
    entities = json.loads((bundle_root / ENTITIES_NAME).read_text(encoding="utf-8"))
    report = ImportReport(dry_run=opts.dry_run, bundle_id=manifest.get("bundle_id", ""))

    manifest_files: list[dict[str, Any]] = manifest.get("files") or []
    account_files: dict[tuple[str, str], list[str]] = {}
    for am in manifest.get("accounts") or []:
        key = (am.get("platform", ""), am.get("username", ""))
        account_files[key] = list(am.get("session_files") or [])

    label_map: dict[str, str] = {}
    proxy_id_by_bundle_label: dict[str, int] = {}

    for pentity in entities.get("proxies") or []:
        blabel = (pentity.get("label") or "").strip()
        effective = _resolve_proxy(db, pentity, label_map, opts, report)
        if effective is None:
            continue
        if not opts.dry_run:
            proxy = db.scalar(select(Proxy).where(Proxy.label == effective))
            if proxy is not None:
                proxy_id_by_bundle_label[blabel] = proxy.id

    for aentity in entities.get("accounts") or []:
        platform_s = aentity.get("platform", "")
        username = aentity.get("username", "")
        account_key = f"{platform_s}:{username}"
        try:
            platform = Platform(platform_s)
        except ValueError:
            report.errors.append(f"unknown platform: {platform_s}")
            continue

        existing = db.scalar(
            select(Account).where(Account.username == username, Account.platform == platform)
        )
        rel_paths = account_files.get((platform_s, username), [])

        if existing is not None and opts.skip_existing_accounts:
            report.accounts_skipped.append(
                {"key": account_key, "reason": "already in database"}
            )
            if opts.merge_session_files:
                _copy_bundle_files(
                    bundle_root,
                    manifest_files,
                    rel_paths,
                    data_dir=data_dir,
                    opts=opts,
                    report=report,
                    account_key=account_key,
                    is_new_account=False,
                )
            continue

        if existing is not None and not opts.skip_existing_accounts:
            report.accounts_skipped.append(
                {"key": account_key, "reason": "exists (skip_existing_accounts=false not implemented)"}
            )
            continue

        bundle_plabel = (aentity.get("proxy_label") or "").strip()
        effective_plabel = label_map.get(bundle_plabel, bundle_plabel)
        proxy_id: int | None = None
        if effective_plabel:
            if opts.dry_run:
                proxy_id = proxy_id_by_bundle_label.get(bundle_plabel)
            else:
                proxy = db.scalar(select(Proxy).where(Proxy.label == effective_plabel))
                if proxy is None:
                    report.errors.append(f"proxy not found for account {account_key}: {effective_plabel}")
                    continue
                proxy_id = proxy.id

        if opts.dry_run:
            report.accounts_added.append(account_key)
        else:
            _apply_account_entity(db, aentity, proxy_id)
            report.accounts_added.append(account_key)
            if platform is Platform.instagram:
                patch_device_app_profile_file(username)

        _copy_bundle_files(
            bundle_root,
            manifest_files,
            rel_paths,
            data_dir=data_dir,
            opts=opts,
            report=report,
            account_key=account_key,
            is_new_account=True,
        )

    return report


def load_bundle_from_archive(archive_path: Path) -> tuple[Path, bool]:
    """Returns (bundle_root, is_temp). Caller should rmtree parent if is_temp."""
    archive_path = archive_path.resolve()
    if archive_path.is_dir():
        inner = archive_path / BUNDLE_ROOT
        if inner.is_dir():
            return inner, False
        if (archive_path / MANIFEST_NAME).is_file():
            return archive_path, False
        raise MigrationBundleError(f"not a bundle directory: {archive_path}")

    tmp = tempfile.mkdtemp(prefix="migration-import-")
    with tarfile.open(archive_path, "r:*") as tar:
        _tar_extractall(tar, tmp)
    inner = Path(tmp) / BUNDLE_ROOT
    if not inner.is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
        raise MigrationBundleError("archive missing migration-bundle-v1/")
    return inner, True
