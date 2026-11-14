"""Run panel assistant for a Telegram chat and report progress."""
from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session

from app.assistant.chat import RUN_ROUNDS, Answer, AssistantError, Step, ask, stream
from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.telegram.format import format_answer, format_progress_step

logger = get_logger(__name__)


def run_agent_task(
    db: Session,
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    allow_browser: bool = True,
    viewer_role: str = "owner",
    account_id: int | None = None,
    job_id: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> Answer:
    settings = settings or get_settings()
    last_progress = 0.0
    progress_min_interval = 3.0

    def maybe_progress(text: str) -> None:
        nonlocal last_progress
        if not on_progress:
            return
        now = time.monotonic()
        if now - last_progress < progress_min_interval:
            return
        last_progress = now
        try:
            on_progress(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.progress_callback_failed", error=str(exc))

    last: Answer | None = None
    try:
        for step in stream(
            db,
            messages,
            settings=settings,
            token=settings.admin_token or None,
            account_id=account_id,
            job_id=job_id,
            allow_browser=allow_browser,
            rounds=RUN_ROUNDS,
            viewer_role=viewer_role,
        ):
            if isinstance(step, Answer):
                last = step
            elif isinstance(step, Step):
                if step.kind in ("tool", "progress", "status", "wire", "generation"):
                    maybe_progress(
                        format_progress_step(step.kind, step.text, getattr(step, "name", None))
                    )
    except AssistantError:
        raise
    if last is None:
        raise AssistantError("Ассистент не вернул ответ", retryable=True)
    return last


def run_agent_task_simple(
    db: Session,
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    allow_browser: bool = True,
    viewer_role: str = "owner",
    account_id: int | None = None,
    job_id: int | None = None,
) -> Answer:
    """Blocking ask() without progress (used in tests)."""
    return ask(
        db,
        messages,
        settings=settings,
        token=(settings or get_settings()).admin_token or None,
        account_id=account_id,
        job_id=job_id,
        allow_browser=allow_browser,
        rounds=RUN_ROUNDS,
        viewer_role=viewer_role,
    )


def final_telegram_text(answer: Answer, *, settings: Settings | None = None) -> str:
    return format_answer(answer, settings=settings)
