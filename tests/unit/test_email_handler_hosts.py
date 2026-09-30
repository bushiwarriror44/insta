"""IMAP host resolution for email challenge."""
from app.accounts.email_handler import _resolve_host, imap_configuration_error


def test_onet_pl_resolves_default_host():
    assert _resolve_host("shop@onet.pl", None) == "imap.poczta.onet.pl"


def test_imap_host_override():
    assert _resolve_host("x@unknown.example", "imap.custom.test") == "imap.custom.test"


def test_imap_configuration_error_unknown_domain():
    err = imap_configuration_error("x@unknown.example", None)
    assert err is not None
    assert "imap_host" in err
