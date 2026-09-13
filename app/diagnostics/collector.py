"""Persist step-by-step diagnostic logs for connection tests and publish jobs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models import (
    DiagnosticRun,
    DiagnosticRunKind,
    DiagnosticRunStatus,
    Event,
    EventLevel,
)

LogLevel = Literal["info", "warn", "error"]
RunStatus = Literal["ok", "warn", "fail"]

LOGIN_EVENT_KINDS = frozenset(
    {
        DiagnosticRunKind.connection_test,
        DiagnosticRunKind.first_login,
        DiagnosticRunKind.mint_mobile_session,
        DiagnosticRunKind.browser_session,
    }
)


@dataclass
class DiagnosticLogLine:
    ts: str
    level: LogLevel
    step: str
    message: str


def _parse_lines(raw: str) -> list[DiagnosticLogLine]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    lines: list[DiagnosticLogLine] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        lines.append(
            DiagnosticLogLine(
                ts=str(item.get("ts", "")),
                level=item.get("level", "info"),  # type: ignore[arg-type]
                step=str(item.get("step", "")),
                message=str(item.get("message", "")),
            )
        )
    return lines


def lines_to_dicts(lines: list[DiagnosticLogLine]) -> list[dict]:
    return [asdict(line) for line in lines]


class DiagnosticCollector:
    """Append-only diagnostic log for a single connection test or publish attempt."""

    def __init__(
        self,
        db: Session,
        *,
        kind: DiagnosticRunKind,
        account_id: int,
        job_id: int | None = None,
    ) -> None:
        self._db = db
        self._lines: list[DiagnosticLogLine] = []
        self._run = DiagnosticRun(
            kind=kind,
            account_id=account_id,
            job_id=job_id,
            status=DiagnosticRunStatus.running,
            lines_json="[]",
        )
        db.add(self._run)
        db.commit()
        db.refresh(self._run)

    @property
    def run_id(self) -> int:
        return self._run.id

    @property
    def lines(self) -> list[DiagnosticLogLine]:
        return list(self._lines)

    def log(self, level: LogLevel, step: str, message: str) -> None:
        line = DiagnosticLogLine(
            ts=datetime.now(timezone.utc).isoformat(),
            level=level,
            step=step,
            message=message,
        )
        self._lines.append(line)
        self._run.lines_json = json.dumps(lines_to_dicts(self._lines), ensure_ascii=False)
        self._db.commit()

    def info(self, step: str, message: str) -> None:
        self.log("info", step, message)

    def warn(self, step: str, message: str) -> None:
        self.log("warn", step, message)

    def error(self, step: str, message: str) -> None:
        self.log("error", step, message)

    def finish(self, status: RunStatus, summary: str) -> None:
        self._run.status = DiagnosticRunStatus(status)
        self._run.summary = summary
        self._run.finished_at = datetime.now(timezone.utc)
        if status in ("fail", "warn") and self._run.kind in LOGIN_EVENT_KINDS:
            kind = self._run.kind.value if hasattr(self._run.kind, "value") else str(self._run.kind)
            level = EventLevel.error if status == "fail" else EventLevel.warn
            self._db.add(
                Event(
                    account_id=self._run.account_id,
                    level=level,
                    kind=kind,
                    message=summary,
                )
            )
        self._db.commit()

    def callback(self) -> "LogCallback":
        return LogCallback(self)


class LogCallback:
    """Adapter for on_log(level, step, message) hooks in publisher/uniquifier."""

    def __init__(self, collector: DiagnosticCollector) -> None:
        self._collector = collector

    def __call__(self, level: str, step: str, message: str) -> None:
        if level == "warn":
            self._collector.warn(step, message)
        elif level == "error":
            self._collector.error(step, message)
        else:
            self._collector.info(step, message)


def load_run_lines(run: DiagnosticRun) -> list[DiagnosticLogLine]:
    return _parse_lines(run.lines_json)
