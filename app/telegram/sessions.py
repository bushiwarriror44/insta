"""In-memory Telegram chat sessions (conversation context for the agent)."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class TelegramChatSession:
    chat_id: int
    messages: list[dict[str, str]] = field(default_factory=list)
    account_id: int | None = None
    job_id: int | None = None
    busy: bool = False
    pending_ask: str | None = None
    pending_ask_options: list[str] = field(default_factory=list)

    def append_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text.strip()})
        self._trim()

    def append_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text.strip()})
        self._trim()

    def _trim(self, max_messages: int = 16) -> None:
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]

    def thread(self) -> list[dict[str, str]]:
        return list(self.messages)


class TelegramSessionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[int, TelegramChatSession] = {}

    def get(self, chat_id: int) -> TelegramChatSession:
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is None:
                session = TelegramChatSession(chat_id=chat_id)
                self._sessions[chat_id] = session
            return session

    def clear(self, chat_id: int) -> None:
        with self._lock:
            self._sessions.pop(chat_id, None)


session_store = TelegramSessionStore()
