from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.browser.chrome_profile_lock import lock_holder_pid, release_chrome_profile_lock


def test_release_removes_lock_when_pid_dead(tmp_path: Path):
    profile = tmp_path / "chrome_profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.write_text("8fb17417f409-99999\n", encoding="utf-8")
    (profile / "SingletonSocket").write_bytes(b"x")

    with patch("app.browser.chrome_profile_lock.process_alive", return_value=False):
        removed = release_chrome_profile_lock(profile)

    assert "SingletonLock" in removed
    assert not lock.exists()


def test_release_keeps_lock_when_pid_alive(tmp_path: Path):
    profile = tmp_path / "chrome_profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.write_text("host-12345\n", encoding="utf-8")

    with patch("app.browser.chrome_profile_lock.process_alive", return_value=True):
        removed = release_chrome_profile_lock(profile)

    assert removed == []
    assert lock.exists()


def test_lock_holder_parses_pid(tmp_path: Path):
    profile = tmp_path / "p"
    profile.mkdir()
    (profile / "SingletonLock").write_text("container-54\n", encoding="utf-8")
    assert lock_holder_pid(profile) == 54
