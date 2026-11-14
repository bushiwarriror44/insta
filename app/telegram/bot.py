"""Long-polling Telegram agent bot."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.assistant.chat import Answer
from app.config import Settings, get_settings
from app.db import Event, EventLevel, SessionLocal
from app.logging_setup import get_logger
from app.telegram import api_client
from app.telegram.auth import (
    HELP_TEXT,
    WELCOME_UNAUTH,
    handle_auth_command,
    handle_logout,
    is_authorized,
    viewer_role,
)
from app.telegram.format import ASK_CALLBACK_PREFIX, ask_reply_markup
from app.telegram.runner import final_telegram_text, run_agent_task
from app.telegram.sessions import session_store

logger = get_logger(__name__)

_last_message_at: dict[int, float] = {}
_rate_lock = threading.Lock()

_agent_executor_pool: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_agent_executor(cfg: Settings) -> ThreadPoolExecutor:
    global _agent_executor_pool
    with _executor_lock:
        workers = cfg.telegram_agent_worker_threads
        if _agent_executor_pool is None:
            _agent_executor_pool = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="tg-agent",
            )
        return _agent_executor_pool


def reset_agent_executor_for_tests() -> None:
    """Shut down the module executor (unit tests only)."""
    global _agent_executor_pool
    with _executor_lock:
        if _agent_executor_pool is not None:
            _agent_executor_pool.shutdown(wait=False, cancel_futures=True)
            _agent_executor_pool = None


def _rate_limited(chat_id: int, cfg: Settings) -> bool:
    if cfg.telegram_agent_rate_limit_s <= 0:
        return False
    with _rate_lock:
        now = time.monotonic()
        prev = _last_message_at.get(chat_id, 0.0)
        if now - prev < cfg.telegram_agent_rate_limit_s:
            return True
        _last_message_at[chat_id] = now
    return False


def _parse_command(text: str) -> tuple[str | None, str]:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None, raw
    parts = raw.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    return cmd, rest


def _format_agent_event_message(chat_id: int, answer: Answer) -> str:
    reply = (answer.reply or "").strip()
    if len(reply) > 300:
        reply = reply[:297].rstrip() + "…"
    parts = [f"chat {chat_id}", reply or "(пусто)"]
    used = list(answer.used or [])[:8]
    if used:
        parts.append("used=" + ",".join(used))
    if answer.asks:
        parts.append(f"asks={len(answer.asks)}")
    return " | ".join(parts)


def _persist_telegram_event(
    message: str,
    *,
    kind: str = "telegram_agent",
    level: EventLevel = EventLevel.info,
) -> None:
    try:
        with SessionLocal() as db:
            db.add(Event(level=level, kind=kind, message=message[:2000]))
            db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("telegram.event_failed", error=str(exc))


def _run_agent_for_chat(chat_id: int, raw_text: str, cfg: Settings) -> None:
    token = api_client.agent_bot_token(cfg)
    session = session_store.get(chat_id)
    text = (raw_text or "").strip()
    if session.pending_ask:
        text = f"Уточнения: {text}"
        session.pending_ask = None

    session.append_user(text)
    status_msg = api_client.send_message(token, chat_id, "Выполняю…")

    with SessionLocal() as db:
        role = viewer_role(db, chat_id)
    allow_browser = role == "owner"

    def on_progress(line: str) -> None:
        if status_msg is None:
            return
        try:
            api_client.edit_message_text(
                token,
                chat_id,
                status_msg,
                f"Выполняю…\n{line}",
            )
        except api_client.TelegramApiError:
            pass

    try:
        with SessionLocal() as db:
            answer = run_agent_task(
                db,
                session.thread(),
                settings=cfg,
                allow_browser=allow_browser,
                viewer_role=role,
                account_id=session.account_id,
                job_id=session.job_id,
                on_progress=on_progress,
            )
        session.append_assistant(answer.reply or "")
        if answer.asks:
            session.pending_ask_options = list(answer.asks[:5])
        else:
            session.pending_ask_options = []
        markup = ask_reply_markup(list(answer.asks or []))
        out = final_telegram_text(answer, settings=cfg)
        tool_errors = list(getattr(answer, "tool_errors", []) or [])
        err_text = "; ".join(tool_errors) if tool_errors else None
        if err_text and err_text not in out:
            out = f"Ошибка: {err_text}\n\n{out}".strip()
        from app.assistant.reports import record_agent_report, report_screenshot_urls

        with SessionLocal() as report_db:
            row = record_agent_report(
                report_db,
                source="telegram",
                prompt=text,
                reply=out,
                error=err_text,
                images=list(answer.images or []),
                settings=cfg,
                token=cfg.admin_token or None,
            )
            shot_urls = report_screenshot_urls(row, cfg)
        if markup:
            if status_msg is not None:
                try:
                    api_client.edit_message_text(token, chat_id, status_msg, out)
                except api_client.TelegramApiError:
                    pass
            api_client.send_message(token, chat_id, "Выберите вопрос или ответьте текстом:", reply_markup=markup)
        elif status_msg is not None:
            try:
                api_client.edit_message_text(token, chat_id, status_msg, out)
            except api_client.TelegramApiError:
                api_client.send_message(token, chat_id, out)
        else:
            api_client.send_message(token, chat_id, out)
        for shot in shot_urls:
            name = shot.split("?", 1)[0].rstrip("/").split("/")[-1]
            path = cfg.screenshots_dir / name
            if path.is_file():
                try:
                    api_client.send_photo(token, chat_id, path, caption=out[:900])
                except api_client.TelegramApiError:
                    logger.warning("telegram.photo_failed", name=name)
        _persist_telegram_event(_format_agent_event_message(chat_id, answer))
    except Exception as exc:
        logger.exception("telegram.agent_run_failed")
        err = str(exc).strip() or "ошибка"
        shown = f"Ошибка: {err[:800]}"
        shot_urls = []
        try:
            from app.assistant.reports import record_agent_report, report_screenshot_urls

            with SessionLocal() as report_db:
                row = record_agent_report(
                    report_db,
                    source="telegram",
                    prompt=text,
                    reply=shown,
                    error=err,
                    images=[],
                    settings=cfg,
                    token=cfg.admin_token or None,
                )
                shot_urls = report_screenshot_urls(row, cfg)
        except Exception:
            logger.exception("telegram.report_failed")
        api_client.send_message(token, chat_id, shown)
        for shot in shot_urls:
            name = shot.split("?", 1)[0].rstrip("/").split("/")[-1]
            path = cfg.screenshots_dir / name
            if path.is_file():
                try:
                    api_client.send_photo(token, chat_id, path, caption=shown[:900])
                except api_client.TelegramApiError:
                    logger.warning("telegram.photo_failed", name=name)
        _persist_telegram_event(
            f"chat {chat_id} | {err[:400]}",
            kind="telegram_agent_error",
            level=EventLevel.warning,
        )
    finally:
        session.busy = False


def handle_callback_query(callback: dict[str, Any], *, cfg: Settings | None = None) -> None:
    cfg = cfg or get_settings()
    token = api_client.agent_bot_token(cfg)
    if not token:
        return
    cb_id = str(callback.get("id") or "")
    data = str(callback.get("data") or "")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    try:
        chat_id = int(chat.get("id"))
    except (TypeError, ValueError):
        return
    if _rate_limited(chat_id, cfg):
        return

    with SessionLocal() as db:
        if not is_authorized(db, chat_id):
            if cb_id:
                try:
                    api_client.answer_callback_query(token, cb_id, text="Нужна /auth")
                except api_client.TelegramApiError:
                    pass
            return

    session = session_store.get(chat_id)
    if data.startswith(ASK_CALLBACK_PREFIX):
        try:
            index = int(data[len(ASK_CALLBACK_PREFIX) :])
        except ValueError:
            index = -1
        options = session.pending_ask_options
        if index < 0 or index >= len(options):
            if cb_id:
                try:
                    api_client.answer_callback_query(token, cb_id, text="Вопрос устарел")
                except api_client.TelegramApiError:
                    pass
            return
        question = options[index]
        session.pending_ask = question
        if cb_id:
            try:
                api_client.answer_callback_query(token, cb_id)
            except api_client.TelegramApiError:
                pass
        api_client.send_message(
            token,
            chat_id,
            f"Ответьте следующим сообщением:\n\n{question}",
        )


def handle_update(update: dict[str, Any], *, cfg: Settings | None = None) -> None:
    cfg = cfg or get_settings()
    if update.get("callback_query"):
        handle_callback_query(update["callback_query"], cfg=cfg)
        return

    token = api_client.agent_bot_token(cfg)
    if not token:
        return
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    try:
        chat_id = int(chat.get("id"))
    except (TypeError, ValueError):
        return
    text = str(message.get("text") or "").strip()
    if not text:
        return
    if _rate_limited(chat_id, cfg):
        return

    cmd, args = _parse_command(text)
    with SessionLocal() as db:
        if cmd in ("/start", "/help"):
            body = HELP_TEXT if is_authorized(db, chat_id) else WELCOME_UNAUTH
            api_client.send_message(token, chat_id, body)
            return
        if cmd == "/auth":
            reply = handle_auth_command(db, chat_id, args)
            api_client.send_message(token, chat_id, reply)
            return
        if cmd == "/logout":
            reply = handle_logout(db, chat_id)
            session_store.clear(chat_id)
            api_client.send_message(token, chat_id, reply)
            return
        if cmd == "/reset":
            session_store.clear(chat_id)
            api_client.send_message(token, chat_id, "История диалога очищена.")
            return
        if cmd == "/status":
            if is_authorized(db, chat_id):
                role = viewer_role(db, chat_id)
                api_client.send_message(
                    token,
                    chat_id,
                    f"Авторизован (роль: {role}). Ollama: {cfg.agent_base_url} / {cfg.agent_model}",
                )
            else:
                api_client.send_message(token, chat_id, "Не авторизован. /auth <token>")
            return
        if not is_authorized(db, chat_id):
            api_client.send_message(token, chat_id, WELCOME_UNAUTH)
            return

    session = session_store.get(chat_id)
    if session.busy:
        api_client.send_message(token, chat_id, "Уже выполняю предыдущее задание…")
        return
    if len(text) > cfg.telegram_agent_max_message_len:
        api_client.send_message(token, chat_id, "Сообщение слишком длинное.")
        return

    session.busy = True
    try:
        _get_agent_executor(cfg).submit(_run_agent_for_chat, chat_id, text, cfg)
    except Exception:
        session.busy = False
        raise


def run_polling(*, cfg: Settings | None = None, once: bool = False) -> None:
    cfg = cfg or get_settings()
    token = api_client.agent_bot_token(cfg)
    if not token:
        raise RuntimeError("Задайте TELEGRAM_BOT_TOKEN или TELEGRAM_AGENT_BOT_TOKEN")
    if not cfg.telegram_agent_enabled:
        raise RuntimeError("Включите TELEGRAM_AGENT_ENABLED=true")

    offset: int | None = None
    timeout = cfg.telegram_agent_poll_timeout_s
    logger.info("telegram.agent_polling_start", timeout=timeout)
    while True:
        try:
            updates = api_client.get_updates(token, offset=offset, timeout=timeout)
        except api_client.TelegramApiError as exc:
            logger.warning("telegram.poll_failed", error=str(exc))
            time.sleep(5)
            if once:
                break
            continue
        for upd in updates:
            try:
                uid = int(upd.get("update_id", 0))
                offset = uid + 1
            except (TypeError, ValueError):
                pass
            try:
                handle_update(upd, cfg=cfg)
            except Exception as exc:  # noqa: BLE001
                logger.exception("telegram.handle_update_failed", error=str(exc))
        if once and not updates:
            break
        if once:
            break
