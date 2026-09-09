"""Reading the reference material a channel points the agent at.

Everything read here ends up in a model's context, and that model writes
captions published under the operator's name and queues renders that cost
money. Text arriving from outside is therefore treated as hostile input,
not as instruction:

* **URLs are allow-listed by host.** An agent that can fetch anything can
  be pointed at a page whose text says "ignore the brief and write this".
  Empty allowlist means no URL source works, which is the safe default.
* **Private addresses are refused** even when the host resolves to one.
  The server can reach its own API, the model runtime and a cloud
  metadata endpoint; a URL source must not become a way in.
* **Files are confined to one directory.** Reading `.env` would hand every
  key the operator has to a model and, through a caption, to the internet.
* **Content is capped and labelled.** The prompt marks it as material to
  draw on, never as instructions to follow.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import Settings, get_settings
from app.db.models import SourceKind
from app.services.http import client as http_client

#: Plain text a person could have written. A PDF or a spreadsheet would
#: need parsing, and parsing untrusted binaries is its own problem.
ALLOWED_FILE_SUFFIXES = {".txt", ".md", ".markdown"}

#: Enough for a page of notes; a whole site would drown the brief.
MAX_CHARS_PER_SOURCE = 4000

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_MARKUP = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\n{3,}")


class SourceError(RuntimeError):
    pass


@dataclass(slots=True)
class SourceText:
    label: str
    origin: str
    text: str


def allowed_hosts(settings: Settings) -> set[str]:
    return {
        host.strip().lower()
        for host in settings.reference_allowed_hosts.split(",")
        if host.strip()
    }


def _is_public(host: str) -> bool:
    """False for anything that resolves to a private or local address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SourceError(f"{host} does not resolve") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            return False
    return True


def check_url(url: str, settings: Settings) -> str:
    """Validate a URL source, returning its host. Raises `SourceError`."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SourceError("only http and https sources are read")

    host = (parsed.hostname or "").lower()
    if not host:
        raise SourceError("that URL has no host")

    permitted = allowed_hosts(settings)
    if not permitted:
        raise SourceError(
            "no hosts are allowed — set REFERENCE_ALLOWED_HOSTS to the sites "
            "the agent may read"
        )
    # A subdomain of an allowed host counts; an unrelated host that merely
    # ends with the same letters does not.
    if not any(
        host == allowed or host.endswith(f".{allowed}") for allowed in permitted
    ):
        raise SourceError(f"{host} is not in REFERENCE_ALLOWED_HOSTS")

    if not _is_public(host):
        raise SourceError(f"{host} resolves to a private address")

    return host


def to_text(body: str) -> str:
    """Strip markup down to something a model can read."""
    without_code = _TAG.sub(" ", body)
    stripped = _MARKUP.sub(" ", without_code)
    collapsed = _SPACE.sub("\n\n", stripped)
    return "\n".join(line.strip() for line in collapsed.splitlines() if line.strip())


def read_url(url: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    check_url(url, settings)

    try:
        with http_client(
            settings,
            timeout=settings.reference_timeout_seconds,
            # A redirect could otherwise land on a host nobody allowed.
            follow_redirects=False,
        ) as client:
            response = client.get(url, headers={"User-Agent": "content-factory/1.0"})
    except httpx.RequestError as exc:
        raise SourceError(f"could not reach {url}: {exc}") from exc

    if response.is_redirect:
        raise SourceError("that URL redirects; point the source at the destination")
    if response.status_code >= 400:
        raise SourceError(f"{url} answered {response.status_code}")

    body = response.content[: settings.reference_max_bytes].decode(
        response.encoding or "utf-8", errors="replace"
    )
    text = to_text(body)
    if not text:
        raise SourceError("that page had no readable text")
    return text[:MAX_CHARS_PER_SOURCE]


def resolve_reference(filename: str, settings: Settings) -> Path:
    """Resolve a reference filename, refusing to leave its directory."""
    root = Path(settings.reference_dir).resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root:
        raise SourceError("that filename escapes the reference directory")
    if candidate.suffix.lower() not in ALLOWED_FILE_SUFFIXES:
        raise SourceError(
            f"only {', '.join(sorted(ALLOWED_FILE_SUFFIXES))} files are read"
        )
    return candidate


def read_file(filename: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    path = resolve_reference(filename, settings)

    if not path.is_file():
        raise SourceError(f"{filename} is not in the reference directory")

    body = path.read_bytes()[: settings.reference_max_bytes].decode(
        "utf-8", errors="replace"
    )
    text = body.strip()
    if not text:
        raise SourceError(f"{filename} is empty")
    return text[:MAX_CHARS_PER_SOURCE]


def read_source(
    kind: SourceKind, value: str, label: str = "", settings: Settings | None = None
) -> SourceText:
    settings = settings or get_settings()
    text = (
        read_url(value, settings)
        if kind is SourceKind.url
        else read_file(value, settings)
    )
    return SourceText(label=label or value, origin=value, text=text)
