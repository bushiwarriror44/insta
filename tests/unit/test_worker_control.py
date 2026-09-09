"""Starting and stopping the worker from the panel."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services import worker_control
from app.services.worker_control import WorkerProblem


@pytest.fixture(autouse=True)
def own_pid_file(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_control, "_pid_file", lambda: tmp_path / "worker.pid")


def spawning(pid: int = 4242) -> MagicMock:
    process = MagicMock()
    process.pid = pid
    return patch("app.services.worker_control.subprocess.Popen", return_value=process)


def alive(yes: bool):
    return patch(
        "app.services.worker_control.os.kill",
        side_effect=None if yes else ProcessLookupError,
    )


def test_ensure_started_skips_when_another_heartbeat_is_alive():
    with spawning() as popen:
        started = worker_control.ensure_started(heartbeat_alive=True)

    assert started is None
    assert popen.call_count == 0


def test_ensure_started_starts_when_nothing_is_running():
    with spawning(), alive(True):
        started = worker_control.ensure_started(heartbeat_alive=False)

    assert started is not None
    assert started.pid == 4242


def test_starting_one_records_it_so_a_restarted_panel_still_knows():
    with spawning(), alive(True):
        started = worker_control.start()

        assert started.alive is True
        assert started.pid == 4242
        assert worker_control.status().pid == 4242


def test_the_command_is_fixed_and_carries_nothing_from_a_request():
    with spawning() as popen, alive(True):
        worker_control.start()

    argv = popen.call_args.args[0]
    assert argv[0] == sys.executable
    assert argv[1:4] == ["-m", "app.cli", "run-worker"]
    assert isinstance(argv, list)
    assert "shell" not in popen.call_args.kwargs
    if sys.platform == "win32":
        import subprocess

        assert popen.call_args.kwargs["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert popen.call_args.kwargs["start_new_session"] is True


def test_starting_twice_does_not_start_a_second_one():
    with spawning() as popen, alive(True):
        worker_control.start()
        again = worker_control.start()

    assert popen.call_count == 1
    assert again.pid == 4242


def test_a_worker_that_died_is_no_longer_reported_as_running():
    with spawning(), alive(True):
        worker_control.start()

    with alive(False):
        assert worker_control.status().alive is False


def test_stopping_asks_the_process_to_finish():
    with spawning(), alive(True):
        worker_control.start()

    with alive(True), patch("app.services.worker_control._ask_to_stop") as asked:
        worker_control.stop()

    assert asked.call_args.args == (4242,)


def test_stopping_nothing_is_not_an_error():
    assert worker_control.stop().alive is False


def test_a_start_that_the_machine_refuses_is_reported():
    with (
        patch(
            "app.services.worker_control.subprocess.Popen",
            side_effect=OSError("no fork"),
        ),
        pytest.raises(WorkerProblem, match="не удалось запустить"),
    ):
        worker_control.start()


def test_a_pid_file_of_nonsense_is_ignored_rather_than_fatal(tmp_path):
    (tmp_path / "worker.pid").write_text("not a pid")

    assert worker_control.status().alive is False
