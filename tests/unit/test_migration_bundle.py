"""Tests for migration bundle export/import merge."""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import Account, Platform, Proxy
from app.proxies.pool import normalize_proxy_url
from app.services import migration_bundle as mb


@pytest.fixture()
def data_dirs(app_env, tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "playwright" / "youtube" / "ytuser").mkdir(parents=True)
    (data / "playwright" / "youtube" / "ytuser" / "state.json").write_text(
        '{"cookies": []}', encoding="utf-8"
    )
    (data / "devices").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "playwright_dir", data / "playwright")
    monkeypatch.setattr(settings, "devices_dir", data / "devices")
    monkeypatch.setattr(settings, "sessions_dir", data / "sessions")
    return data


def test_export_bundle_contains_manifest(db_session, data_dirs, tmp_path):
    proxy = Proxy(label="p1", url="http://u:p@1.2.3.4:8000", country="US")
    db_session.add(proxy)
    db_session.commit()
    db_session.refresh(proxy)

    account = Account(
        username="ytuser",
        platform=Platform.youtube,
        password="secret",
        proxy_id=proxy.id,
    )
    db_session.add(account)
    db_session.commit()

    out = tmp_path / "bundle.tar.gz"
    result = mb.export_migration_bundle(db_session, out)
    assert result.account_count == 1
    assert result.file_count >= 1

    with tarfile.open(result.bundle_path, "r:gz") as tar:
        names = tar.getnames()
    assert f"{mb.BUNDLE_ROOT}/{mb.MANIFEST_NAME}" in names
    assert f"{mb.BUNDLE_ROOT}/{mb.ENTITIES_NAME}" in names


def test_import_adds_account_and_reuses_proxy(db_session, data_dirs, tmp_path):
    proxy = Proxy(label="p1", url="http://u:p@1.2.3.4:8000", country="US")
    db_session.add(proxy)
    db_session.commit()
    db_session.refresh(proxy)

    account = Account(
        username="ytuser",
        platform=Platform.youtube,
        password="secret",
        proxy_id=proxy.id,
    )
    db_session.add(account)
    db_session.commit()

    out = tmp_path / "bundle.tar.gz"
    mb.export_migration_bundle(db_session, out)

    db_session.delete(account)
    db_session.commit()

    bundle_root, is_temp = mb.load_bundle_from_archive(out)
    try:
        report = mb.import_migration_bundle(
            db_session,
            bundle_root,
            mb.ImportOptions(prefix="qa-"),
            cfg=settings,
        )
    finally:
        if is_temp:
            import shutil

            shutil.rmtree(bundle_root.parent, ignore_errors=True)

    assert "youtube:ytuser" in report.accounts_added
    row = db_session.scalar(
        select(Account).where(Account.username == "ytuser", Account.platform == Platform.youtube)
    )
    assert row is not None
    assert row.password == "secret"


def test_proxy_label_conflict_remapped(db_session, data_dirs, tmp_path):
    for row in db_session.scalars(select(Proxy)).all():
        db_session.delete(row)
    for row in db_session.scalars(select(Account)).all():
        db_session.delete(row)
    db_session.commit()

    bundle_proxy = Proxy(label="p1", url="http://u:p@1.2.3.4:8000", country="US")
    db_session.add(bundle_proxy)
    db_session.commit()
    db_session.refresh(bundle_proxy)

    account = Account(
        username="yt2",
        platform=Platform.youtube,
        password="x",
        proxy_id=bundle_proxy.id,
    )
    db_session.add(account)
    db_session.commit()

    out = tmp_path / "bundle.tar.gz"
    mb.export_migration_bundle(db_session, out)

    db_session.delete(account)
    db_session.delete(bundle_proxy)
    db_session.commit()

    server_proxy = Proxy(label="p1", url="http://other:pass@9.9.9.9:8000", country="DE")
    db_session.add(server_proxy)
    db_session.commit()

    bundle_root, is_temp = mb.load_bundle_from_archive(out)
    try:
        report = mb.import_migration_bundle(
            db_session,
            bundle_root,
            mb.ImportOptions(prefix="qa-"),
            cfg=settings,
        )
    finally:
        if is_temp:
            import shutil

            shutil.rmtree(bundle_root.parent, ignore_errors=True)

    assert report.proxies_remapped.get("p1", "").startswith("qa-p1")
    new_label = report.proxies_remapped["p1"]
    proxy = db_session.scalar(select(Proxy).where(Proxy.label == new_label))
    assert proxy is not None
    assert normalize_proxy_url(proxy.url) == normalize_proxy_url("http://u:p@1.2.3.4:8000")


def test_skip_existing_account(db_session, data_dirs, tmp_path):
    proxy = Proxy(label="p1", url="http://u:p@1.2.3.4:8000")
    db_session.add(proxy)
    db_session.commit()
    db_session.refresh(proxy)

    account = Account(
        username="ytuser",
        platform=Platform.youtube,
        password="old",
        proxy_id=proxy.id,
    )
    db_session.add(account)
    db_session.commit()

    out = tmp_path / "bundle.tar.gz"
    account.password = "new"
    db_session.commit()
    mb.export_migration_bundle(db_session, out)

    bundle_root, is_temp = mb.load_bundle_from_archive(out)
    try:
        report = mb.import_migration_bundle(
            db_session,
            bundle_root,
            mb.ImportOptions(),
            cfg=settings,
        )
    finally:
        if is_temp:
            import shutil

            shutil.rmtree(bundle_root.parent, ignore_errors=True)

    assert report.accounts_added == []
    assert any(s["key"] == "youtube:ytuser" for s in report.accounts_skipped)
    row = db_session.scalar(
        select(Account).where(Account.username == "ytuser", Account.platform == Platform.youtube)
    )
    assert row is not None
    assert row.password == "new"


def test_file_skip_when_dest_exists(db_session, data_dirs, tmp_path):
    proxy = Proxy(label="p1", url="http://u:p@1.2.3.4:8000")
    db_session.add(proxy)
    db_session.commit()
    db_session.refresh(proxy)

    state_path = data_dirs / "playwright" / "youtube" / "ytuser" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"cookies": [{"name": "a"}]}', encoding="utf-8")

    account = Account(
        username="ytuser",
        platform=Platform.youtube,
        password="s",
        proxy_id=proxy.id,
    )
    db_session.add(account)
    db_session.commit()

    out = tmp_path / "bundle.tar.gz"
    mb.export_migration_bundle(db_session, out)

    db_session.delete(account)
    db_session.commit()
    state_path.write_text('{"cookies": [{"name": "local"}]}', encoding="utf-8")

    bundle_root, is_temp = mb.load_bundle_from_archive(out)
    try:
        report = mb.import_migration_bundle(
            db_session,
            bundle_root,
            mb.ImportOptions(),
            cfg=settings,
        )
    finally:
        if is_temp:
            import shutil

            shutil.rmtree(bundle_root.parent, ignore_errors=True)

    assert "youtube:ytuser" in report.accounts_added
    assert state_path.read_text(encoding="utf-8") == '{"cookies": [{"name": "local"}]}'
    assert any(f["reason"] == "dest exists" for f in report.files_skipped)


def test_url_fingerprint_stable():
    a = mb.url_fingerprint("http://user:pass@host:8000")
    b = mb.url_fingerprint("http://user:pass@host:8000")
    assert a == b
    assert a != mb.url_fingerprint("http://other:pass@host:8000")
