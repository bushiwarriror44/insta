"""Unit tests for backup code parsing."""
from __future__ import annotations

import pytest

from app.accounts.backup_codes import (
    consume_next_backup_code,
    parse_account_line,
    parse_backup_codes_text,
    serialize_backup_codes,
)


def test_parse_backup_codes_text_space_separated():
    codes = parse_backup_codes_text("JUJW WLWP QGPU 2YQW")
    assert codes == ["JUJW", "WLWP", "QGPU", "2YQW"]


def test_parse_backup_codes_text_json():
    codes = parse_backup_codes_text('["ABCD EFGH", "IJKL"]')
    assert codes == ["ABCDEFGH", "IJKL"]


def test_parse_account_line_full():
    line = (
        "maisielambert8:Ygt7Rns4OYU:JUJW WLWP QGPU 2YQW YO3V:https://www.instagram.com/maisielambert8/"
    )
    parsed = parse_account_line(line)
    assert parsed["username"] == "maisielambert8"
    assert parsed["password"] == "Ygt7Rns4OYU"
    assert len(parsed["backup_codes"]) == 5
    assert parsed["profile_url"].startswith("https://")


def test_consume_next_backup_code(app_env):
    from app.db import Account

    db = app_env.SessionLocal()
    account = Account(username="backup_user", password="pw")
    db.add(account)
    account.backup_codes = serialize_backup_codes(["AAAA", "BBBB"])
    db.commit()

    first = consume_next_backup_code(db, account)
    second = consume_next_backup_code(db, account)
    third = consume_next_backup_code(db, account)

    assert first == "AAAA"
    assert second == "BBBB"
    assert third is None


def test_parse_account_line_invalid():
    with pytest.raises(ValueError):
        parse_account_line("onlyusername")
