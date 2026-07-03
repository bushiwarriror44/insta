"""Tests for app.accounts.challenge."""
from __future__ import annotations

import threading
import time

import pytest

from app.accounts import challenge as ch_module


def test_write_code_creates_file(app_env):
    ch_module.write_code("alice", "123456")
    path = ch_module.CHALLENGES_DIR / "alice.code"
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "123456"


def test_handler_picks_up_code_and_deletes_file(app_env):
    handler = ch_module.make_handler("bob", timeout_sec=5)

    def _drop():
        time.sleep(0.05)
        ch_module.write_code("bob", "654321")

    threading.Thread(target=_drop, daemon=True).start()
    code = handler("bob", "EMAIL")
    assert code == "654321"
    assert not (ch_module.CHALLENGES_DIR / "bob.code").exists()


def test_handler_times_out(app_env, monkeypatch):
    monkeypatch.setattr(ch_module.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        ch_module.time,
        "monotonic",
        _CountingClock([0.0, 0.0, 99999.0, 99999.0]),
    )
    handler = ch_module.make_handler("ghost", timeout_sec=1)
    with pytest.raises(TimeoutError):
        handler("ghost", "SMS")


def test_handler_invokes_on_request_and_swallows_callback_error(app_env):
    seen = []

    def cb(username, choice):
        seen.append((username, str(choice)))
        raise RuntimeError("boom")

    handler = ch_module.make_handler("carol", on_request=cb, timeout_sec=5)

    def _drop():
        time.sleep(0.05)
        ch_module.write_code("carol", "0001")

    threading.Thread(target=_drop, daemon=True).start()
    code = handler("carol", "EMAIL")
    assert code == "0001"
    assert seen == [("carol", "EMAIL")]


def test_handler_clears_existing_stale_file(app_env):
    ch_module.write_code("dave", "STALE")
    handler = ch_module.make_handler("dave", timeout_sec=5)

    def _drop():
        time.sleep(0.05)
        ch_module.write_code("dave", "FRESH")

    threading.Thread(target=_drop, daemon=True).start()
    code = handler("dave", "EMAIL")
    assert code == "FRESH"


class _CountingClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        if self.values:
            return self.values.pop(0)
        return 99999.0
