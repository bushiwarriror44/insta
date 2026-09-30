"""Tests for seller tab-line account parsing."""
from app.accounts.vendor_line import looks_like_vendor_line, parse_vendor_line


def test_parse_vendor_line_tab_separated():
    line = "iguser\tsecretpass\tbuyer@onet.pl\tmailpass123"
    out = parse_vendor_line(line)
    assert out == {
        "username": "iguser",
        "password": "secretpass",
        "email": "buyer@onet.pl",
        "email_password": "mailpass123",
    }


def test_looks_like_vendor_line_rejects_colon_style():
    assert looks_like_vendor_line("user:pass:code1") is False


def test_looks_like_vendor_line_accepts_tab_email():
    assert looks_like_vendor_line("u\tp\ta@b.c\tep") is True


def test_parse_vendor_line_semicolon():
    out = parse_vendor_line("u; p; x@y.z; ep")
    assert out["username"] == "u"
    assert out["email"] == "x@y.z"
