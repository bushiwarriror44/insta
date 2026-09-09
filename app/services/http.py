"""One place that builds an HTTP client, so one place decides its egress.

There were twenty-six `httpx.Client(...)` calls across the platform
adapters, the render backend, the agent and the reference reader. Adding
a proxy meant finding all of them and remembering the next one — which
is the kind of rule that holds until someone adds a twenty-seventh.

The proxy is per-process and not per-channel. A fixed egress address is
an ordinary requirement: some corporate networks and some API allowlists
only accept traffic from one. Binding a different address to each account
would be something else entirely, and this is deliberately not that.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.config import Settings, get_settings

#: The variables every other HTTP library in this process reads. The
#: YouTube adapter goes through googleapiclient and httplib2, neither of
#: which takes a client from here.
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")


def client(settings: Settings | None = None, **kwargs: Any) -> httpx.Client:
    """An `httpx.Client` that honours `OUTBOUND_PROXY`.

    Everything else is passed through, so a caller keeps its own timeout,
    headers and redirect policy.
    """
    settings = settings or get_settings()
    if settings.outbound_proxy:
        kwargs.setdefault("proxy", settings.outbound_proxy)
    return httpx.Client(**kwargs)


def apply_outbound_proxy(settings: Settings | None = None) -> str | None:
    """Put the proxy where libraries that take no client will find it.

    Called once at startup. An address the operator already exported wins
    — this fills a gap rather than overriding a decision, and a setting
    that silently replaced the environment would be the worse surprise of
    the two.

    Returns the address in use, or None.
    """
    settings = settings or get_settings()
    if not settings.outbound_proxy:
        return None

    for name in PROXY_VARS:
        os.environ.setdefault(name, settings.outbound_proxy)
    return os.environ["HTTPS_PROXY"]
