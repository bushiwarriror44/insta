"""Tests for app.accounts.email_handler.

We don't stand up a real IMAP server; instead we verify host detection and
the graceful-degradation paths (missing dependency, login failure, no code).
"""
from __future__ import annotations

import builtins
from unittest.mock import MagicMock


from app.accounts import email_handler as eh


def test_resolve_host_known_providers():
    assert eh._resolve_host("user@gmail.com", None) == "imap.gmail.com"
    assert eh._resolve_host("user@yandex.ru", None) == "imap.yandex.ru"
    assert eh._resolve_host("user@outlook.com", None) == "outlook.office365.com"


def test_resolve_host_explicit_override_wins():
    assert eh._resolve_host("user@gmail.com", "custom.host") == "custom.host"


def test_resolve_host_unknown_returns_none():
    assert eh._resolve_host("user@unknown-corp.test", None) is None


def test_resolve_host_garbage_email():
    assert eh._resolve_host("not-an-email", None) is None


def test_fetch_returns_none_when_imap_tools_missing(monkeypatch):
    """If imap-tools is not installed, the function returns None silently."""
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "imap_tools":
            raise ImportError("imap_tools not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert eh.fetch_instagram_code("u@gmail.com", "pw") is None


def test_fetch_returns_none_when_host_unknown():
    """Mail providers we don't have a default IMAP host for fall through."""
    assert eh.fetch_instagram_code("user@unknown-provider.test", "pw") is None


def test_fetch_returns_none_on_imap_error(monkeypatch):
    """Login or fetch errors must not propagate — return None and let the
    caller fall back to the file-based or Telegram-based flow."""
    fake_mailbox_cls = MagicMock()
    fake_instance = MagicMock()
    fake_instance.login.side_effect = RuntimeError("imap creds rejected")
    fake_mailbox_cls.return_value = fake_instance

    fake_module = MagicMock()
    fake_module.MailBox = fake_mailbox_cls
    fake_module.AND = lambda **kw: kw

    monkeypatch.setitem(__import__("sys").modules, "imap_tools", fake_module)
    assert eh.fetch_instagram_code("u@gmail.com", "pw", timeout_sec=1) is None


def test_fetch_extracts_six_digit_code_from_instagram_email(monkeypatch):
    """Happy path: a matching message yields the 6-digit code."""
    msg = MagicMock()
    msg.from_ = "security@mail.instagram.com"
    msg.text = "Your Instagram security code is 482910. It will expire shortly."
    msg.html = ""
    msg.subject = "Verify your account"
    msg.date = None  # cutoff check is a soft filter

    fake_box = MagicMock()
    fake_box.fetch.return_value = iter([msg])

    fake_mailbox_cls = MagicMock()
    fake_mailbox_cls.return_value.login.return_value.__enter__.return_value = fake_box
    fake_mailbox_cls.return_value.login.return_value.__exit__.return_value = False

    fake_module = MagicMock()
    fake_module.MailBox = fake_mailbox_cls
    fake_module.AND = lambda **kw: kw

    monkeypatch.setitem(__import__("sys").modules, "imap_tools", fake_module)
    code = eh.fetch_instagram_code("u@gmail.com", "pw", timeout_sec=1, poll_sec=0.0)
    assert code == "482910"


def test_fetch_skips_unrelated_senders(monkeypatch):
    """Codes inside emails from non-Instagram senders must be ignored."""
    msg = MagicMock()
    msg.from_ = "stranger@example.com"
    msg.text = "Code: 999999"
    msg.html = ""
    msg.subject = "spam"
    msg.date = None

    fake_box = MagicMock()
    fake_box.fetch.return_value = iter([msg])

    fake_mailbox_cls = MagicMock()
    fake_mailbox_cls.return_value.login.return_value.__enter__.return_value = fake_box
    fake_mailbox_cls.return_value.login.return_value.__exit__.return_value = False

    fake_module = MagicMock()
    fake_module.MailBox = fake_mailbox_cls
    fake_module.AND = lambda **kw: kw

    monkeypatch.setitem(__import__("sys").modules, "imap_tools", fake_module)
    code = eh.fetch_instagram_code(
        "u@gmail.com", "pw", timeout_sec=1, poll_sec=0.0
    )
    assert code is None
