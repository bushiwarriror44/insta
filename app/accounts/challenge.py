"""Challenge handler glue for instagrapi.

The instagrapi Client expects a callable ``challenge_code_handler(username,
choice) -> str`` that returns the verification code. We support three
strategies:

1. Fetch from a file ``data/challenges/<username>.code`` — fast manual flow
   for ops: when an alert hits Telegram, drop the code into the file.
2. Telegram bot — currently a stub for the alert; the answer can be written
   into the file via a Telegram-controlled side channel.
3. Manual stdin (last resort, for interactive sessions).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

try:
    from instagrapi.mixins.challenge import ChallengeChoice
except ImportError:  # pragma: no cover - older instagrapi releases
    from instagrapi.types import ChallengeChoice  # type: ignore[no-redef]

from app.config import settings
from app.logging_setup import get_logger

logger = get_logger(__name__)

CHALLENGES_DIR = settings.data_dir / "challenges"
CHALLENGES_DIR.mkdir(parents=True, exist_ok=True)


def _code_file(username: str) -> Path:
    return CHALLENGES_DIR / f"{username}.code"


def write_code(username: str, code: str) -> None:
    _code_file(username).write_text(code.strip(), encoding="utf-8")


def _wait_for_code(username: str, timeout_sec: int = 300, poll_sec: int = 3) -> str | None:
    path = _code_file(username)
    if path.exists():
        path.unlink(missing_ok=True)

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if path.exists():
            try:
                code = path.read_text(encoding="utf-8").strip()
            except OSError:
                code = ""
            if code:
                path.unlink(missing_ok=True)
                return code
        time.sleep(poll_sec)
    return None


def make_handler(
    username: str,
    on_request: Callable[[str, ChallengeChoice], None] | None = None,
    timeout_sec: int = 300,
    *,
    email: str | None = None,
    email_password: str | None = None,
) -> Callable[[str, ChallengeChoice], str]:
    """Return a ``challenge_code_handler`` bound to a specific account.

    Resolution order for the verification code:

    1. If ``email``/``email_password`` are supplied, attempt an IMAP poll
       against the major email providers (handled by
       :mod:`app.accounts.email_handler`). This is fully unattended.
    2. Wait for the code to appear in ``data/challenges/<username>.code``,
       written by an operator (Telegram bot, manual ops UI, etc.).
    3. If both fail within ``timeout_sec``, raise ``TimeoutError``.
    """

    def handler(handler_username: str, choice: ChallengeChoice) -> str:
        logger.warning(
            "challenge.requested",
            username=handler_username,
            choice=str(choice),
            file_to_drop_code=str(_code_file(handler_username)),
        )
        if on_request is not None:
            try:
                on_request(handler_username, choice)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("challenge.notify_failed", username=handler_username, error=str(exc))

        if email and email_password:
            from app.accounts.email_handler import fetch_instagram_code

            try:
                code = fetch_instagram_code(
                    email=email,
                    email_password=email_password,
                    timeout_sec=min(60, timeout_sec),
                )
            except Exception as exc:  # noqa: BLE001 - never fail the login from email path
                logger.warning("challenge.email_handler_error", error=str(exc))
                code = None
            if code:
                logger.info("challenge.code_via_email", username=handler_username)
                return code

        code = _wait_for_code(handler_username, timeout_sec=timeout_sec)
        if not code:
            logger.error("challenge.timeout", username=handler_username)
            raise TimeoutError(f"No challenge code provided for {handler_username} within {timeout_sec}s")

        logger.info("challenge.code_received", username=handler_username, choice=str(choice))
        return code

    return handler
