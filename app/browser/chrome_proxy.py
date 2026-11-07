"""Parse upstream proxy URLs for native Chrome (no credentials in --proxy-server)."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.proxies.pool import normalize_proxy_url

_KNOWN_SCHEMES = frozenset({"http", "https", "socks4", "socks5"})
_SCHEME_ALIASES = {"socks5h": "socks5", "socks4a": "socks4"}


@dataclass(frozen=True)
class ChromeUpstreamProxy:
    scheme: str
    server: str
    host: str
    port: int
    username: str | None
    password: str | None

    @property
    def needs_auth(self) -> bool:
        return bool((self.username or "").strip())

    @property
    def is_http_family(self) -> bool:
        return self.scheme in ("http", "https")

    def chrome_proxy_server_value(self) -> str:
        """Value for ``--proxy-server=`` without embedded credentials."""
        return self.server


def _normalize_scheme(scheme: str) -> str:
    lowered = (scheme or "http").strip().lower()
    return _SCHEME_ALIASES.get(lowered, lowered)


def parse_chrome_upstream(proxy_url: str) -> ChromeUpstreamProxy:
    normalized = normalize_proxy_url((proxy_url or "").strip())
    if not normalized:
        raise ValueError("пустой URL прокси")

    if "://" not in normalized:
        normalized = f"http://{normalized}"

    parsed = urlparse(normalized)
    scheme = _normalize_scheme(parsed.scheme or "http")
    if scheme not in _KNOWN_SCHEMES:
        raise ValueError(f"схема прокси не поддерживается в Chrome: {scheme}")

    host = parsed.hostname
    if not host:
        raise ValueError(f"не удалось разобрать host прокси: {normalized}")

    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 1080 if scheme.startswith("socks") else 80

    username = parsed.username
    password = parsed.password
    server = f"{scheme}://{host}:{port}"
    if "@" in server:
        raise ValueError("в server всё ещё есть credentials — баг парсера")

    return ChromeUpstreamProxy(
        scheme=scheme,
        server=server,
        host=host,
        port=port,
        username=username,
        password=password,
    )


def chrome_proxy_server_flag(proxy_server_value: str) -> str | None:
    value = (proxy_server_value or "").strip()
    if not value:
        return None
    if "@" in value:
        raise ValueError("Chrome --proxy-server не должен содержать credentials")
    return f"--proxy-server={value}"


def native_chrome_proxy_blocked_reason(upstream: ChromeUpstreamProxy) -> str | None:
    if upstream.needs_auth and not upstream.is_http_family:
        return (
            "Native Chrome не поддерживает SOCKS-прокси с логином. "
            "Используйте HTTP-прокси или STUDIO_VNC_NATIVE_CHROME=false (Playwright)."
        )
    return None
