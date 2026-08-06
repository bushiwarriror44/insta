"""instagrapi Client lifecycle: device fingerprint -> proxy -> session.

Critically fixes the original bug where ``client.login(username, password)``
was called unconditionally after ``load_settings`` — this forced a fresh
auth handshake on every run, defeating session persistence and inviting
checkpoints.

Correct flow implemented here:
1. ``client.set_settings(saved_fp.settings)``           -> restore device + uuids
2. ``client.set_locale / country / timezone_offset``   -> consistent geo
3. ``client.set_proxy(proxy_url)``                     -> sticky proxy
4. If a saved session exists -> ``load_settings`` then call a cheap
   authed endpoint (``get_timeline_feed``) to validate.
5. Only on ``LoginRequired`` exception do we call ``client.login``.
6. After every successful auth or session-validate, we ``dump_settings``
   to keep cookies fresh.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Optional

from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    ClientError,
    LoginRequired,
    PleaseWaitFewMinutes,
    TwoFactorRequired,
)

from app.accounts.device_factory import (
    DeviceFingerprint,
    get_or_create_fingerprint,
    rotate_session_uuids,
    save_fingerprint,
)
from app.accounts.session_cookie import normalize_sessionid, sessionid_diag_label
from app.config import settings
from app.logging_setup import get_logger

logger = get_logger(__name__)

DiagCallback = Callable[[Literal["info", "warn", "error"], str, str], None]


class AuthenticationError(Exception):
    pass


class HardCheckpoint(AuthenticationError):
    """Raised when the account is locked beyond what code-handler can solve."""


class ProxyRequiredError(AuthenticationError):
    """Raised before any Instagram network call when no proxy is configured."""


def session_path(username: str) -> Path:
    return settings.sessions_dir / f"session_{username}.json"


def session_id_for_mobile_login(username: str, db_session_id: str | None) -> str | None:
    """DB sessionid for mobile login only when a mobile dump exists.

    Dolphin/browser web cookies often live in the DB without ``session_*.json``.
    Passing those to ``login_by_sessionid`` wastes ~2 minutes and still fails;
    callers should fall through to password login instead.
    """
    if not session_path(username).exists():
        return None
    return normalize_sessionid(db_session_id)


def clear_session_file(username: str) -> bool:
    """Remove persisted instagrapi session for *username* (e.g. after sessionid import)."""
    path = session_path(username)
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("session.clear_failed", username=username, error=str(exc))
        return False
    logger.info("session.file_cleared", username=username, path=str(path))
    return True


def _load_session_settings(client: Client, username: str) -> bool:
    path = session_path(username)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("session.load_failed", username=username, error=str(exc))
        return False
    try:
        client.set_settings(data)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("session.set_settings_failed", username=username, error=str(exc))
        return False
    return True


def _dump_session_settings(client: Client, username: str) -> None:
    path = session_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.dump_settings(str(path))
        logger.info("session.persisted", username=username, path=str(path))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("session.dump_failed", username=username, error=str(exc))


def _account_username_from_info(info: object) -> Optional[str]:
    if info is None:
        return None
    if isinstance(info, dict):
        value = info.get("username")
    else:
        value = getattr(info, "username", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resume_from_session_file(
    client: Client,
    username: str,
    proxy_url: str,
    log,
) -> Optional[Client]:
    """Load ``session_{username}.json`` and return *client* if the session is alive."""
    had_session = _load_session_settings(client, username)
    if had_session:
        client.set_proxy(proxy_url)
    if not had_session:
        return None
    try:
        if _validate_session(client):
            log.info("session.resumed")
            _dump_session_settings(client, username)
            return client
        log.info("session.expired_attempting_relogin")
    except ChallengeRequired as exc:
        log.warning("session.challenge_required_on_resume")
        raise HardCheckpoint(str(exc)) from exc
    return None


def build_client(
    username: str,
    fingerprint: DeviceFingerprint,
    proxy_url: Optional[str] = None,
    challenge_handler: Optional[Callable[[str, object], str]] = None,
    request_timeout: int = 30,
) -> Client:
    """Create an instagrapi Client with the persistent fingerprint applied."""
    proxy_url = (proxy_url or "").strip()
    if not proxy_url:
        raise ProxyRequiredError(f"proxy_url is required for Instagram account '{username}'")

    client = Client(request_timeout=request_timeout)

    # Apply fingerprint BEFORE any network call.
    client.set_settings(fingerprint.settings)
    client.set_user_agent(fingerprint.user_agent)
    client.set_device(fingerprint.settings["device_settings"])
    client.set_locale(fingerprint.locale)
    client.set_country(fingerprint.country)
    client.set_country_code(fingerprint.country_code)
    client.set_timezone_offset(fingerprint.timezone_offset)

    client.set_proxy(proxy_url)

    if challenge_handler is not None:
        client.challenge_code_handler = challenge_handler

    return client


def _validate_session(client: Client) -> bool:
    """Cheap authed call. Returns True if the session is alive."""
    try:
        client.get_timeline_feed()
        return True
    except LoginRequired:
        return False
    except (ChallengeRequired, PleaseWaitFewMinutes):
        raise
    except ClientError as exc:
        logger.warning("session.validate_client_error", error=str(exc))
        return False


def _normalize_verification_code(explicit: Optional[str]) -> Optional[str]:
    """Normalize 2FA input: strip spaces; 8-digit backup codes stay digits-only."""
    if not explicit:
        return None
    cleaned = "".join(explicit.split())
    if re.fullmatch(r"\d{8}", cleaned):
        return cleaned
    return cleaned or None


def _resolve_verification_code(
    explicit: Optional[str], totp_seed: Optional[str], log
) -> Optional[str]:
    """Return a 2FA code: explicit value wins, otherwise compute from TOTP seed."""
    normalized = _normalize_verification_code(explicit)
    if normalized:
        if re.fullmatch(r"\d{8}", normalized):
            log.info("auth.backup_code_provided")
        return normalized
    if not totp_seed:
        return None
    try:
        import pyotp  # local import keeps cold-start cheap
    except ImportError:  # pragma: no cover - dependency declared in requirements.txt
        log.warning("auth.pyotp_missing")
        return None
    try:
        cleaned = "".join(totp_seed.split()).upper()
        code = pyotp.TOTP(cleaned).now()
        log.info("auth.totp_generated")
        return code
    except Exception as exc:  # noqa: BLE001 - bad seed → no code, still try login
        log.warning("auth.totp_failed", error=str(exc))
        return None


def _try_login_by_sessionid(
    client: Client,
    session_id: str,
    expected_username: str,
    log,
) -> bool:
    """Attempt ``login_by_sessionid``; return True if session validates for *expected_username*."""
    session_id = normalize_sessionid(session_id) or ""
    if len(session_id) <= 30:
        log.warning("auth.session_id_too_short")
        return False
    try:
        client.login_by_sessionid(session_id)
    except (AssertionError, ClientError, LoginRequired) as exc:
        log.warning("auth.session_id_rejected", error=str(exc))
        return False
    except Exception as exc:  # noqa: BLE001 - fall through to password login
        log.warning("auth.session_id_failed", error=str(exc))
        return False
    try:
        if not _validate_session(client):
            return False
        actual = _account_username_from_info(client.account_info())
        if actual and actual.lower() != expected_username.lower():
            log.warning(
                "auth.session_id_username_mismatch",
                expected=expected_username,
                actual=actual,
            )
            raise AuthenticationError(
                f"session_id belongs to @{actual}, not @{expected_username}"
            )
        return True
    except ChallengeRequired:
        raise
    except PleaseWaitFewMinutes:
        raise


def login_or_resume(
    username: str,
    password: str,
    fingerprint: DeviceFingerprint,
    proxy_url: Optional[str] = None,
    challenge_handler: Optional[Callable[[str, object], str]] = None,
    verification_code: Optional[str] = None,
    totp_seed: Optional[str] = None,
    session_id: Optional[str] = None,
    login_identifier: Optional[str] = None,
) -> Client:
    """Return a logged-in Client for a single account (one Client per call).

    Isolation contract:
    - Session files live at ``session_{username}.json`` only for that username.
    - ``session_id`` must belong to the same ``username`` (verified via account_info).
    - When ``session_id`` is set in the DB it is tried before the on-disk session file.

    ``totp_seed`` (Base32 string) is used to compute a one-time ``verification_code``
    locally via :mod:`pyotp` when an explicit code was not supplied.
    """
    log = logger.bind(username=username)
    proxy_url = (proxy_url or "").strip()
    stripped_sid = normalize_sessionid(session_id) or ""
    login_id = (login_identifier or username).strip()

    def _fresh_client() -> Client:
        return build_client(
            username=username,
            fingerprint=fingerprint,
            proxy_url=proxy_url,
            challenge_handler=challenge_handler,
        )

    client = _fresh_client()

    if stripped_sid:
        try:
            if _try_login_by_sessionid(client, stripped_sid, username, log):
                log.info("session.resumed_via_sessionid")
                _dump_session_settings(client, username)
                return client
            log.info("session.sessionid_invalid_trying_file_or_password")
        except ChallengeRequired as exc:
            log.warning("session.challenge_required_on_sessionid")
            raise HardCheckpoint(str(exc)) from exc
        except AuthenticationError:
            raise
        client = _fresh_client()

    resumed = _resume_from_session_file(client, username, proxy_url, log)
    if resumed is not None:
        return resumed

    client = _fresh_client()
    code = _resolve_verification_code(verification_code, totp_seed, log)

    def _do_login(with_code: Optional[str]) -> None:
        if with_code:
            client.login(login_id, password, verification_code=with_code)
        else:
            client.login(login_id, password)

    try:
        _do_login(code)
    except BadPassword as exc:
        log.error("auth.bad_password")
        raise AuthenticationError("bad password") from exc
    except TwoFactorRequired as exc:
        # Server demanded a code but our explicit one was missing/invalid.
        # Last-chance: derive from totp_seed and retry once.
        retry_code = _resolve_verification_code(None, totp_seed, log) if not code else None
        if retry_code:
            try:
                _do_login(retry_code)
            except Exception as inner:  # noqa: BLE001
                log.error("auth.2fa_retry_failed", error=str(inner))
                raise AuthenticationError("2FA code rejected") from inner
        else:
            log.error("auth.2fa_required_no_code")
            raise AuthenticationError("2FA code required: pass verification_code or totp_seed") from exc
    except ChallengeRequired as exc:
        log.warning("auth.challenge_required")
        # instagrapi will invoke challenge_code_handler under the hood.
        # If that handler couldn't solve the challenge, the underlying
        # exception propagates. Treat that as a hard checkpoint.
        raise HardCheckpoint(str(exc)) from exc
    except PleaseWaitFewMinutes as exc:
        log.warning("auth.rate_limited")
        raise AuthenticationError("rate-limited by Instagram, retry later") from exc
    except ClientError as exc:
        log.error("auth.client_error", error=str(exc))
        raise AuthenticationError(str(exc)) from exc

    _dump_session_settings(client, username)
    log.info("auth.login_success")
    return client


def login_and_export_sessionid(
    username: str,
    password: str,
    fingerprint: DeviceFingerprint,
    proxy_url: str,
    *,
    totp_seed: str | None = None,
    login_identifier: str | None = None,
    challenge_handler=None,
) -> str:
    """Password-login via instagrapi and return the resulting sessionid."""
    from app.accounts.session_cookie import MIN_SESSIONID_LEN
    from app.accounts.session_export import export_sessionid

    login_or_resume(
        username=username,
        password=password,
        fingerprint=fingerprint,
        proxy_url=proxy_url,
        totp_seed=totp_seed,
        session_id=None,
        login_identifier=login_identifier,
        challenge_handler=challenge_handler,
    )
    exported = export_sessionid(username)
    if exported is None or len(exported.session_id) < MIN_SESSIONID_LEN:
        raise AuthenticationError("API login completed but sessionid is missing")
    return exported.session_id


@dataclass(frozen=True)
class ProbeSessionResult:
    ok: bool
    method: Literal["sessionid", "session_file", "none"]
    ig_username: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[Literal["session_missing", "session_expired", "challenge_required"]] = None
    challenge: bool = False


def probe_session_auth(
    username: str,
    fingerprint: DeviceFingerprint,
    proxy_url: str,
    session_id: Optional[str] = None,
    *,
    diag: DiagCallback | None = None,
) -> ProbeSessionResult:
    """Validate an existing session without password fallback (admin diagnostics)."""
    log = logger.bind(username=username)
    proxy_url = (proxy_url or "").strip()
    stripped_sid = normalize_sessionid(session_id) or ""
    started = time.monotonic()
    file_exists = session_path(username).exists()

    def _d(level: Literal["info", "warn", "error"], step: str, message: str) -> None:
        if diag is not None:
            diag(level, step, message)

    def _elapsed() -> str:
        ms = int((time.monotonic() - started) * 1000)
        return f"elapsed_ms={ms}"

    def _fresh_client() -> Client:
        return build_client(
            username=username,
            fingerprint=fingerprint,
            proxy_url=proxy_url,
        )

    _d(
        "info",
        "session_probe",
        f"Старт: DB sessionid={sessionid_diag_label(stripped_sid or None)}, "
        f"файл session_*.json={'да' if file_exists else 'нет'}",
    )

    if stripped_sid:
        _d(
            "info",
            "session_probe",
            f"Попытка login_by_sessionid ({sessionid_diag_label(stripped_sid)})",
        )
        client = _fresh_client()
        try:
            if _try_login_by_sessionid(client, stripped_sid, username, log):
                _dump_session_settings(client, username)
                actual = _account_username_from_info(client.account_info())
                _d(
                    "info",
                    "session_probe",
                    f"sessionid OK как @{actual or username}; {_elapsed()}",
                )
                return ProbeSessionResult(
                    ok=True,
                    method="sessionid",
                    ig_username=actual or username,
                )
            _d(
                "warn",
                "session_probe",
                "DB sessionid отклонён (невалиден/истёк) — пробуем session_*.json",
            )
            log.info("session.probe_sessionid_invalid_trying_file")
        except HardCheckpoint as exc:
            _d("warn", "session_probe", f"challenge на sessionid: {exc}; {_elapsed()}")
            return ProbeSessionResult(
                ok=False,
                method="sessionid",
                challenge=True,
                error=str(exc),
                error_code="challenge_required",
            )
        except AuthenticationError as exc:
            _d("error", "session_probe", f"sessionid auth error: {exc}; {_elapsed()}")
            return ProbeSessionResult(ok=False, method="sessionid", error=str(exc))
        except ChallengeRequired as exc:
            _d("warn", "session_probe", f"challenge_required: {exc}; {_elapsed()}")
            return ProbeSessionResult(
                ok=False,
                method="sessionid",
                challenge=True,
                error=str(exc),
                error_code="challenge_required",
            )
        except PleaseWaitFewMinutes as exc:
            _d("error", "session_probe", f"rate-limited: {exc}; {_elapsed()}")
            return ProbeSessionResult(ok=False, method="sessionid", error=str(exc))
        # Match login_or_resume: invalid DB sessionid → try mobile dump before failing.

    if not session_path(username).exists():
        if stripped_sid:
            _d(
                "error",
                "session_probe",
                f"файл сессии отсутствует; DB sid мёртв; {_elapsed()}",
            )
            return ProbeSessionResult(
                ok=False,
                method="sessionid",
                error="session_id недействителен или истёк",
                error_code="session_expired",
            )
        _d("error", "session_probe", f"нет DB sid и нет файла сессии; {_elapsed()}")
        return ProbeSessionResult(
            ok=False,
            method="none",
            error=(
                "Нет session_id в БД и нет файла сессии на диске. "
                "Импортируйте sessionid через панель «Сессия»."
            ),
            error_code="session_missing",
        )

    _d("info", "session_probe", "Загрузка session_*.json (mobile dump)")
    client = _fresh_client()
    try:
        resumed = _resume_from_session_file(client, username, proxy_url, log)
        if resumed is not None:
            actual = _account_username_from_info(resumed.account_info())
            _d(
                "info",
                "session_probe",
                f"session_file OK как @{actual or username}; {_elapsed()}",
            )
            return ProbeSessionResult(
                ok=True,
                method="session_file",
                ig_username=actual or username,
            )
        if stripped_sid:
            _d(
                "error",
                "session_probe",
                f"session_file устарел; DB sid тоже мёртв; {_elapsed()}",
            )
            return ProbeSessionResult(
                ok=False,
                method="sessionid",
                error="session_id недействителен или истёк",
                error_code="session_expired",
            )
        _d("error", "session_probe", f"session_file устарел или недействителен; {_elapsed()}")
        return ProbeSessionResult(
            ok=False,
            method="session_file",
            error="Файл сессии устарел или недействителен",
            error_code="session_expired",
        )
    except HardCheckpoint as exc:
        _d("warn", "session_probe", f"challenge на session_file: {exc}; {_elapsed()}")
        return ProbeSessionResult(
            ok=False,
            method="session_file",
            challenge=True,
            error=str(exc),
            error_code="challenge_required",
        )
    except ChallengeRequired as exc:
        _d("warn", "session_probe", f"challenge_required на file: {exc}; {_elapsed()}")
        return ProbeSessionResult(
            ok=False,
            method="session_file",
            challenge=True,
            error=str(exc),
            error_code="challenge_required",
        )
    except PleaseWaitFewMinutes as exc:
        _d("error", "session_probe", f"rate-limited на file: {exc}; {_elapsed()}")
        return ProbeSessionResult(ok=False, method="session_file", error=str(exc))


def ensure_fingerprint_and_proxy(
    username: str,
    country: str = "US",
    *,
    timezone_id: str | None = None,
) -> DeviceFingerprint:
    """Convenience: get-or-create a device fingerprint for a username.

    When *timezone_id* is set, new fingerprints use that IANA offset; existing
    ones only update ``timezone_offset`` (device identity stays sticky).
    """
    fp = get_or_create_fingerprint(username, country=country, timezone_id=timezone_id)
    save_fingerprint(username, fp)
    return fp


# Session id rotation cadence: a real client doesn't keep the same
# client_session_id / pigeon_session_id forever. We pick a per-call jittered
# threshold in the 3–7 day band so two accounts never rotate on the same
# schedule.
_SESSION_ROTATION_MIN_DAYS = 3
_SESSION_ROTATION_MAX_DAYS = 7


def maybe_rotate_session_uuids(
    username: str,
    fingerprint: DeviceFingerprint,
    last_rotation_at: Optional[datetime],
    *,
    rng: random.Random | None = None,
) -> tuple[bool, DeviceFingerprint]:
    """Rotate ``client_session_id``/``pigeon_session_id`` if enough time has passed.

    Returns ``(rotated, fingerprint)``. The fingerprint is mutated in place
    *and* persisted to disk when a rotation occurs. The caller is responsible
    for updating the ``Account.last_session_rotation_at`` column on success.
    """
    rng = rng or random.Random()
    now = datetime.now(timezone.utc)
    threshold_days = rng.uniform(_SESSION_ROTATION_MIN_DAYS, _SESSION_ROTATION_MAX_DAYS)
    threshold = timedelta(days=threshold_days)

    if last_rotation_at is None:
        # No record at all — opportunistically stamp "now" so we don't rotate
        # on the very first run after deploy. This avoids touching session
        # ids in ways that would invalidate freshly resumed sessions.
        return False, fingerprint
    if last_rotation_at.tzinfo is None:
        last_rotation_at = last_rotation_at.replace(tzinfo=timezone.utc)

    if now - last_rotation_at < threshold:
        return False, fingerprint

    rotate_session_uuids(fingerprint)
    save_fingerprint(username, fingerprint)
    logger.info(
        "session.uuid_rotated",
        username=username,
        days_since=(now - last_rotation_at).total_seconds() / 86400,
    )
    return True, fingerprint
