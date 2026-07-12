"""Tests for Instagram login identifier resolution."""

from types import SimpleNamespace

from app.accounts.first_login_service import _format_auth_error
from app.accounts.login_identifier import is_account_not_found_error, resolve_login_identifier
from app.accounts.session_manager import AuthenticationError


def test_resolve_login_identifier_prefers_explicit():
    account = SimpleNamespace(username="paneluser", login_identifier="user@example.com")
    assert resolve_login_identifier(account) == "user@example.com"


def test_resolve_login_identifier_falls_back_to_username():
    account = SimpleNamespace(username="paneluser", login_identifier=None)
    assert resolve_login_identifier(account) == "paneluser"


def test_resolve_login_identifier_ignores_blank():
    account = SimpleNamespace(username="paneluser", login_identifier="   ")
    assert resolve_login_identifier(account) == "paneluser"


def test_is_account_not_found_error():
    assert is_account_not_found_error("We can't find an account with foo.")
    assert is_account_not_found_error("The username you entered doesn't belong to an account")
    assert not is_account_not_found_error("bad password")


def test_format_auth_error_account_not_found():
    msg = _format_auth_error(
        AuthenticationError("We can't find an account with ge.org7293. Try another mobile number")
    )
    assert "не находит аккаунт" in msg
    assert "Логин Instagram" in msg
