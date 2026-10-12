"""High-level Reels publisher composed from session manager + warmup + uniquify."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from instagrapi.exceptions import (
    ChallengeRequired,
    ClientError,
    FeedbackRequired,
    PleaseWaitFewMinutes,
)

from app.accounts.challenge import make_handler
from app.accounts.session_manager import (
    AuthenticationError,
    HardCheckpoint,
    login_or_resume,
    session_id_for_mobile_login,
)
from app.behavior.humanizer import think
from app.behavior.warmup_instagrapi import warmup
from app.logging_setup import get_logger

logger = get_logger(__name__)

OnLogFn = Callable[[str, str, str], None]


def _emit(on_log: OnLogFn | None, level: str, step: str, message: str) -> None:
    if on_log is not None:
        on_log(level, step, message)


class PublishError(Exception):
    pass


class TemporaryPublishError(PublishError):
    """Retry-able error (rate limits, transient API failures)."""


class HardPublishError(PublishError):
    """Non retry-able (account blocked, bad credentials, hard checkpoint)."""


class ActionCooldownError(PublishError):
    """Soft block — Instagram asks us to slow down (FeedbackRequired / spam-flag).

    Distinct from :class:`HardPublishError` so the worker can place the account
    on a 24–48h cooldown instead of marking it ``blocked``.
    """


# FeedbackRequired surfaces a wide range of messages; the ones below are
# strong indicators that the action was throttled rather than the account
# permanently disabled. We err on the side of cooldown over hard-block.
_COOLDOWN_HINTS = (
    "feedback_required",
    "feedback required",
    "action blocked",
    "spam",
    "try again later",
    "we limit how often",
    "wait a few minutes",
    "wait a few moments",
    "this action was blocked",
)


def _looks_like_cooldown(message: str) -> bool:
    needle = (message or "").lower()
    return any(hint in needle for hint in _COOLDOWN_HINTS)


@dataclass
class PublishResult:
    media_id: str
    media_code: Optional[str]
    final_video_path: Path
    final_caption: str


@dataclass
class MediaStats:
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    play_count: Optional[int] = None
    save_count: Optional[int] = None
    share_count: Optional[int] = None
    raw_json: Optional[str] = None


def _login_media_client(
    *,
    username: str,
    password: str,
    fingerprint,
    proxy_url: Optional[str],
    on_challenge=None,
    totp_seed: Optional[str] = None,
    session_id: Optional[str] = None,
    email: Optional[str] = None,
    email_password: Optional[str] = None,
):
    proxy_url = (proxy_url or "").strip()
    if not proxy_url:
        raise HardPublishError(f"для Instagram-аккаунта «{username}» нужен прокси")

    handler = make_handler(
        username,
        on_request=on_challenge,
        email=email,
        email_password=email_password,
    )
    try:
        return login_or_resume(
            username=username,
            password=password,
            fingerprint=fingerprint,
            proxy_url=proxy_url,
            challenge_handler=handler,
            totp_seed=totp_seed,
            session_id=session_id_for_mobile_login(username, session_id),
            login_identifier=None,
        )
    except HardCheckpoint as exc:
        raise HardPublishError(f"жёсткий checkpoint: {exc}") from exc
    except AuthenticationError as exc:
        msg = str(exc).lower()
        if "rate" in msg or "wait" in msg:
            raise TemporaryPublishError(str(exc)) from exc
        raise HardPublishError(str(exc)) from exc


def _coerce_media_result(media) -> tuple[str, Optional[str]]:
    media_id = str(getattr(media, "pk", "")) or str(getattr(media, "id", ""))
    media_code = getattr(media, "code", None)
    if isinstance(media, dict):
        media_id = str(media.get("pk") or media.get("id") or media_id)
        media_code = media.get("code") or media_code
    return media_id, media_code


def _safe_raw_json(obj) -> Optional[str]:
    try:
        if hasattr(obj, "model_dump"):
            payload = obj.model_dump()
        elif hasattr(obj, "dict"):
            payload = obj.dict()
        elif isinstance(obj, dict):
            payload = obj
        else:
            payload = getattr(obj, "__dict__", {})
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        return None


def _stat_int(obj, *names: str) -> Optional[int]:
    for name in names:
        value = None
        if isinstance(obj, dict):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _extract_stats(info) -> MediaStats:
    return MediaStats(
        view_count=_stat_int(info, "view_count", "views", "view_count_int"),
        like_count=_stat_int(info, "like_count", "likes", "like_count_int"),
        comment_count=_stat_int(info, "comment_count", "comments", "comment_count_int"),
        play_count=_stat_int(info, "play_count", "plays", "ig_play_count"),
        save_count=_stat_int(info, "save_count", "saves"),
        share_count=_stat_int(info, "share_count", "shares"),
        raw_json=_safe_raw_json(info),
    )


def _safe_call(log, name: str, fn, *args, **kwargs) -> None:
    """Run a best-effort post-publish probe; never raises."""
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - best effort
        log.debug("publish.settling_step_failed", step=name, error=str(exc))


def _post_publish_settle(client, log) -> None:
    """Post-publish "settling" pattern.

    A real user does not log out the moment a Reel uploads. They glance at
    their profile, scroll the feed, maybe view a story. We replicate the
    cheapest version of that to break the ``login → upload → vanish`` pattern
    that automated publishers expose to anti-spam heuristics.
    """
    think(median_sec=4.0, max_sec=12.0)

    user_id = getattr(client, "user_id", None)
    if user_id:
        _safe_call(log, "user_info_v1", client.user_info_v1, user_id)
        think(median_sec=3.0, max_sec=10.0)

    _safe_call(log, "get_timeline_feed", client.get_timeline_feed)
    think(median_sec=6.0, max_sec=15.0)


def publish_reel(
    *,
    username: str,
    password: str,
    fingerprint,
    proxy_url: Optional[str],
    video_path: str | Path,
    caption: str,
    do_warmup: bool = True,
    warmup_intensity: str = "normal",
    on_challenge=None,
    totp_seed: Optional[str] = None,
    session_id: Optional[str] = None,
    email: Optional[str] = None,
    email_password: Optional[str] = None,
    on_log: OnLogFn | None = None,
) -> PublishResult:
    """Top-level entry: login (or resume), warm up, then publish."""
    log = logger.bind(username=username)
    video_file = Path(video_path)
    if not video_file.exists():
        raise HardPublishError(f"видео не найдено: {video_file}")

    _emit(on_log, "info", "login", "Авторизация клиента Instagram")
    client = _login_media_client(
        username=username,
        password=password,
        fingerprint=fingerprint,
        proxy_url=proxy_url,
        on_challenge=on_challenge,
        totp_seed=totp_seed,
        session_id=session_id,
        email=email,
        email_password=email_password,
    )
    _emit(on_log, "info", "login", "Клиент авторизован")

    if do_warmup:
        _emit(on_log, "info", "warmup", f"Прогрев перед публикацией ({warmup_intensity})")
        try:
            warmup(client, intensity=warmup_intensity)
            _emit(on_log, "info", "warmup", "Прогрев завершён")
        except Exception as exc:  # warmup is best effort
            log.warning("warmup.failed", error=str(exc))
            _emit(on_log, "warn", "warmup", f"Прогрев не удался (некритично): {exc}")

    think(median_sec=8.0, max_sec=30.0)

    _emit(on_log, "info", "upload", f"Загрузка reel {video_file.name}")
    try:
        media = client.clip_upload(str(video_file), caption=caption)
    except FeedbackRequired as exc:
        # Treat as a soft cooldown if the message indicates throttling.
        # Worker upgrades the account to AccountStatus.cooldown for 24-48h.
        log.warning("publish.feedback_required_cooldown", error=str(exc))
        _emit(on_log, "warn", "upload", f"Требуется обратная связь: {exc}")
        raise ActionCooldownError(str(exc)) from exc
    except ChallengeRequired as exc:
        log.error("publish.challenge_required")
        _emit(on_log, "error", "upload", f"Требуется подтверждение: {exc}")
        raise HardPublishError(f"при публикации нужен challenge: {exc}") from exc
    except PleaseWaitFewMinutes as exc:
        log.warning("publish.rate_limited")
        _emit(on_log, "warn", "upload", f"Лимит запросов: {exc}")
        raise TemporaryPublishError(str(exc)) from exc
    except ClientError as exc:
        msg = str(exc)
        if _looks_like_cooldown(msg):
            log.warning("publish.client_error_cooldown", error=msg)
            _emit(on_log, "warn", "upload", msg)
            raise ActionCooldownError(msg) from exc
        log.error("publish.client_error", error=msg)
        _emit(on_log, "error", "upload", msg)
        raise TemporaryPublishError(msg) from exc
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("publish.unexpected")
        _emit(on_log, "error", "upload", str(exc))
        raise TemporaryPublishError(str(exc)) from exc

    media_id, media_code = _coerce_media_result(media)
    log.info("publish.done", media_id=media_id, media_code=media_code)
    _emit(on_log, "info", "upload", f"Опубликовано media_id={media_id} code={media_code or '-'}")

    try:
        _emit(on_log, "info", "settling", "Пост-публикационная пауза")
        _post_publish_settle(client, log)
        _emit(on_log, "info", "settling", "Пауза завершена")
    except Exception as exc:  # noqa: BLE001 - settling never blocks success
        log.debug("publish.settling_aborted", error=str(exc))
        _emit(on_log, "warn", "settling", f"Пауза прервана: {exc}")

    return PublishResult(
        media_id=media_id,
        media_code=media_code,
        final_video_path=video_file,
        final_caption=caption,
    )


def publish_feed_photo(
    *,
    username: str,
    password: str,
    fingerprint,
    proxy_url: Optional[str],
    image_path: str | Path,
    caption: str,
    on_challenge=None,
    totp_seed: Optional[str] = None,
    session_id: Optional[str] = None,
    email: Optional[str] = None,
    email_password: Optional[str] = None,
    on_log: OnLogFn | None = None,
) -> PublishResult:
    """Publish a single-image feed post."""
    log = logger.bind(username=username, post_type="feed_photo")
    image_file = Path(image_path)
    if not image_file.exists():
        raise HardPublishError(f"изображение не найдено: {image_file}")
    _emit(on_log, "info", "login", "Авторизация клиента Instagram")
    client = _login_media_client(
        username=username,
        password=password,
        fingerprint=fingerprint,
        proxy_url=proxy_url,
        on_challenge=on_challenge,
        totp_seed=totp_seed,
        session_id=session_id,
        email=email,
        email_password=email_password,
    )
    _emit(on_log, "info", "upload", f"Загрузка фото в ленту {image_file.name}")
    try:
        media = client.photo_upload(str(image_file), caption=caption)
    except FeedbackRequired as exc:
        _emit(on_log, "warn", "upload", str(exc))
        raise ActionCooldownError(str(exc)) from exc
    except ChallengeRequired as exc:
        _emit(on_log, "error", "upload", str(exc))
        raise HardPublishError(f"при публикации нужен challenge: {exc}") from exc
    except PleaseWaitFewMinutes as exc:
        _emit(on_log, "warn", "upload", str(exc))
        raise TemporaryPublishError(str(exc)) from exc
    except ClientError as exc:
        msg = str(exc)
        if _looks_like_cooldown(msg):
            _emit(on_log, "warn", "upload", msg)
            raise ActionCooldownError(msg) from exc
        _emit(on_log, "error", "upload", msg)
        raise TemporaryPublishError(msg) from exc
    media_id, media_code = _coerce_media_result(media)
    log.info("publish.feed_photo_done", media_id=media_id, media_code=media_code)
    _emit(on_log, "info", "upload", f"Опубликовано media_id={media_id}")
    _post_publish_settle(client, log)
    return PublishResult(media_id=media_id, media_code=media_code, final_video_path=image_file, final_caption=caption)


def publish_feed_video(
    *,
    username: str,
    password: str,
    fingerprint,
    proxy_url: Optional[str],
    video_path: str | Path,
    caption: str,
    on_challenge=None,
    totp_seed: Optional[str] = None,
    session_id: Optional[str] = None,
    email: Optional[str] = None,
    email_password: Optional[str] = None,
    on_log: OnLogFn | None = None,
) -> PublishResult:
    """Publish a single-video feed post."""
    log = logger.bind(username=username, post_type="feed_video")
    video_file = Path(video_path)
    if not video_file.exists():
        raise HardPublishError(f"видео не найдено: {video_file}")
    _emit(on_log, "info", "login", "Авторизация клиента Instagram")
    client = _login_media_client(
        username=username,
        password=password,
        fingerprint=fingerprint,
        proxy_url=proxy_url,
        on_challenge=on_challenge,
        totp_seed=totp_seed,
        session_id=session_id,
        email=email,
        email_password=email_password,
    )
    _emit(on_log, "info", "upload", f"Загрузка видео в ленту {video_file.name}")
    try:
        media = client.video_upload(str(video_file), caption=caption)
    except FeedbackRequired as exc:
        _emit(on_log, "warn", "upload", str(exc))
        raise ActionCooldownError(str(exc)) from exc
    except ChallengeRequired as exc:
        _emit(on_log, "error", "upload", str(exc))
        raise HardPublishError(f"при публикации нужен challenge: {exc}") from exc
    except PleaseWaitFewMinutes as exc:
        _emit(on_log, "warn", "upload", str(exc))
        raise TemporaryPublishError(str(exc)) from exc
    except ClientError as exc:
        msg = str(exc)
        if _looks_like_cooldown(msg):
            _emit(on_log, "warn", "upload", msg)
            raise ActionCooldownError(msg) from exc
        _emit(on_log, "error", "upload", msg)
        raise TemporaryPublishError(msg) from exc
    media_id, media_code = _coerce_media_result(media)
    log.info("publish.feed_video_done", media_id=media_id, media_code=media_code)
    _emit(on_log, "info", "upload", f"Опубликовано media_id={media_id}")
    _post_publish_settle(client, log)
    return PublishResult(media_id=media_id, media_code=media_code, final_video_path=video_file, final_caption=caption)


def _fetch_media_info(client, media_id: str, log):
    """Try canonical media_info, then media_info_v2 for ad-tagged media."""
    try:
        return client.media_info(media_id)
    except ClientError as exc:
        if not hasattr(client, "media_info_v2"):
            raise
        log.debug("publish.media_info_fallback_v2", error=str(exc))
        return client.media_info_v2(media_id)


def fetch_media_stats(
    *,
    username: str,
    password: str,
    fingerprint,
    proxy_url: Optional[str],
    media_id: str,
    on_challenge=None,
    totp_seed: Optional[str] = None,
    session_id: Optional[str] = None,
    email: Optional[str] = None,
    email_password: Optional[str] = None,
) -> MediaStats:
    """Fetch best-effort counters for a published media object."""
    client = _login_media_client(
        username=username,
        password=password,
        fingerprint=fingerprint,
        proxy_url=proxy_url,
        on_challenge=on_challenge,
        totp_seed=totp_seed,
        session_id=session_id,
        email=email,
        email_password=email_password,
    )
    log = logger.bind(username=username)
    try:
        info = _fetch_media_info(client, media_id, log)
    except PleaseWaitFewMinutes as exc:
        raise TemporaryPublishError(str(exc)) from exc
    except ClientError as exc:
        raise TemporaryPublishError(str(exc)) from exc
    return _extract_stats(info)
