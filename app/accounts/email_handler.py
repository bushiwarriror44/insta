"""Optional IMAP-based Instagram security-code fetcher.

When an account has an ``email`` + ``email_password`` configured, this
module can poll the inbox for the 6-digit verification code Instagram
sends from ``security@mail.instagram.com`` (or similar) and return it
to the challenge handler — fully unattended.

Implementation notes:
* ``imap-tools`` is an *optional* dependency. If it is missing the
  function returns ``None`` and the caller falls back to file-based or
  Telegram-driven manual flow.
* IMAP host is auto-detected from the email domain for the major
  providers (gmail, yahoo, outlook/hotmail, proton, mail.ru, yandex,
  rambler). For everything else, pass ``host`` explicitly.
* The polling window is short (default 60s) and only the last 5 minutes
  worth of mail is scanned to avoid replaying old codes.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.logging_setup import get_logger

logger = get_logger(__name__)


_IMAP_HOSTS: dict[str, str] = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "msn.com": "outlook.office365.com",
    "icloud.com": "imap.mail.me.com",
    "protonmail.com": "imap.protonmail.ch",
    "proton.me": "imap.protonmail.ch",
    "mail.ru": "imap.mail.ru",
    "bk.ru": "imap.mail.ru",
    "list.ru": "imap.mail.ru",
    "inbox.ru": "imap.mail.ru",
    "yandex.ru": "imap.yandex.ru",
    "yandex.com": "imap.yandex.com",
    "rambler.ru": "imap.rambler.ru",
    "onet.pl": "imap.poczta.onet.pl",
    "op.pl": "imap.poczta.onet.pl",
    "wp.pl": "imap.wp.pl",
    "o2.pl": "poczta.o2.pl",
    "interia.pl": "poczta.interia.pl",
}


_INSTAGRAM_FROM_PATTERNS = (
    "@mail.instagram.com",
    "security@mail.instagram.com",
    "no-reply@mail.instagram.com",
    "@facebookmail.com",  # rare but happens on Meta-level checkpoints
)

_CODE_REGEX = re.compile(r"\b(\d{6})\b")


def imap_configuration_error(email: str, host: Optional[str] = None) -> Optional[str]:
    """Human-readable reason IMAP auto-fetch cannot run, or None if it may work."""
    mail = (email or "").strip()
    if not mail:
        return None
    try:
        from imap_tools import MailBox  # noqa: F401
    except ImportError:
        return "imap-tools не установлен — код из почты только вручную"
    if not _resolve_host(mail, (host or "").strip() or None):
        return "неизвестный IMAP-хост — укажите imap_host в карточке аккаунта"
    return None


def _resolve_host(email: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].lower().strip()
    return _IMAP_HOSTS.get(domain)


def fetch_instagram_code(
    email: str,
    email_password: str,
    *,
    host: Optional[str] = None,
    timeout_sec: int = 60,
    poll_sec: float = 4.0,
    look_back_minutes: int = 5,
) -> Optional[str]:
    """Poll the inbox for a 6-digit Instagram verification code.

    Returns ``None`` if ``imap-tools`` is not installed, the host could not
    be resolved, login failed, or no matching email arrived in time.
    """
    try:
        from imap_tools import MailBox, AND  # type: ignore
    except ImportError:
        logger.info("email.imap_tools_not_installed")
        return None

    resolved_host = _resolve_host(email, host)
    if not resolved_host:
        logger.warning("email.host_unknown", email=email)
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=look_back_minutes)
    deadline = time.monotonic() + timeout_sec

    while time.monotonic() < deadline:
        try:
            with MailBox(resolved_host).login(email, email_password) as mailbox:
                # Look at the last few unseen messages from any IG-related sender.
                criteria = AND(seen=False)
                for msg in mailbox.fetch(criteria, reverse=True, limit=10, mark_seen=False):
                    sender = (msg.from_ or "").lower()
                    if not any(pat in sender for pat in _INSTAGRAM_FROM_PATTERNS):
                        continue
                    msg_date = getattr(msg, "date", None)
                    if msg_date is not None:
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        if msg_date < cutoff:
                            continue
                    body = (msg.text or "") + "\n" + (msg.html or "")
                    match = _CODE_REGEX.search(body)
                    if match:
                        code = match.group(1)
                        logger.info(
                            "email.code_found",
                            email=email,
                            sender=sender,
                            subject=getattr(msg, "subject", "")[:80],
                        )
                        return code
        except Exception as exc:  # noqa: BLE001 - any IMAP failure → keep polling/return None
            logger.warning("email.imap_error", email=email, error=str(exc))
            return None

        time.sleep(poll_sec)

    logger.info("email.code_not_found", email=email)
    return None
