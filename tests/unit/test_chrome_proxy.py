from __future__ import annotations

import pytest

from app.browser.chrome_proxy import (
    chrome_proxy_server_flag,
    native_chrome_proxy_blocked_reason,
    parse_chrome_upstream,
)


def test_parse_http_proxy_strips_credentials():
    upstream = parse_chrome_upstream("http://alice:secret@1.2.3.4:8080")
    assert upstream.needs_auth is True
    assert upstream.server == "http://1.2.3.4:8080"
    assert "@" not in upstream.chrome_proxy_server_value()
    assert upstream.host == "1.2.3.4"
    assert upstream.port == 8080


def test_parse_provider_quad_format():
    upstream = parse_chrome_upstream("5.6.7.8:9000:user:pass:word")
    assert upstream.needs_auth is True
    assert upstream.server == "http://5.6.7.8:9000"


def test_chrome_proxy_flag_rejects_credentials():
    with pytest.raises(ValueError):
        chrome_proxy_server_flag("http://user:pass@1.2.3.4:8080")


def test_socks5_auth_blocked_for_native():
    upstream = parse_chrome_upstream("socks5://u:p@host.example:1080")
    reason = native_chrome_proxy_blocked_reason(upstream)
    assert reason is not None
    assert "SOCKS" in reason


def test_socks5_no_auth_ok():
    upstream = parse_chrome_upstream("socks5://host.example:1080")
    assert not upstream.needs_auth
    assert native_chrome_proxy_blocked_reason(upstream) is None
    assert upstream.server == "socks5://host.example:1080"
