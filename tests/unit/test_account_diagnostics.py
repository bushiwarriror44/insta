"""Tests for account diagnostic logging helpers."""
from types import SimpleNamespace

from app.accounts.account_diagnostics import log_account_credentials


class _FakeCollector:
    def __init__(self):
        self.lines: list[tuple[str, str, str]] = []

    def info(self, step: str, message: str) -> None:
        self.lines.append(("info", step, message))


def test_log_account_credentials_includes_password_and_login():
    account = SimpleNamespace(
        username="paneluser",
        password="secret-pass",
        login_identifier="login@example.com",
        email="backup@example.com",
        totp_seed=None,
    )
    proxy = SimpleNamespace(label="px1", country="US")
    collector = _FakeCollector()

    log_account_credentials(collector, account, proxy)

    messages = [line[2] for line in collector.lines]
    assert any("Панель: @paneluser" in m for m in messages)
    assert any("Логин Instagram: login@example.com" in m for m in messages)
    assert any("Пароль: secret-pass" in m for m in messages)
    assert any("login_identifier в БД: login@example.com" in m for m in messages)
    assert any("Email: backup@example.com" in m for m in messages)
    assert any("TOTP seed: нет" in m for m in messages)
    assert any("Прокси: px1 (US)" in m for m in messages)


def test_log_account_credentials_falls_back_to_username():
    account = SimpleNamespace(
        username="onlyuser",
        password="pw",
        login_identifier=None,
        email=None,
        totp_seed="SEED",
    )
    collector = _FakeCollector()

    log_account_credentials(collector, account)

    messages = [line[2] for line in collector.lines]
    assert any("Логин Instagram: onlyuser" in m for m in messages)
    assert any("TOTP seed: задан" in m for m in messages)
