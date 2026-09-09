"""Panel API for starting and stopping the agent."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.scheduler.heartbeat import WorkerStatus
from app.services.worker_control import Running, WorkerProblem


@pytest.fixture()
def api_client(app_env, monkeypatch):
    from app.api import deps as api_deps
    from app.api.main import create_app
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "", raising=True)

    app = create_app()

    def _override_get_db():
        db = app_env.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    return TestClient(app)


def test_worker_status_when_nothing_is_running(api_client):
    res = api_client.get("/api/worker")
    assert res.status_code == 200
    body = res.json()
    assert body["running"] is False
    assert body["ours"] is False
    assert body["pid"] is None


def test_start_and_stop_from_the_panel(api_client):
    with (
        patch("app.api.routes.worker.worker_control.start", return_value=Running(True, 4242)),
        patch("app.api.routes.worker.worker_control.status", return_value=Running(True, 4242)),
        patch(
            "app.api.routes.worker.worker_status",
            return_value=WorkerStatus(name="worker", seen_at=None, stale=True),
        ),
    ):
        started = api_client.post("/api/worker/start")
    assert started.status_code == 200
    assert started.json()["ours"] is True
    assert started.json()["pid"] == 4242

    with (
        patch("app.api.routes.worker.worker_control.status", return_value=Running(True, 4242)),
        patch("app.api.routes.worker.worker_control.stop", return_value=Running(False, 4242)),
        patch(
            "app.api.routes.worker.worker_status",
            return_value=WorkerStatus(name="worker", seen_at=None, stale=True),
        ),
    ):
        stopped = api_client.post("/api/worker/stop")
    assert stopped.status_code == 200


def test_start_refuses_when_an_outside_worker_is_already_alive(api_client):
    from datetime import datetime, timezone

    with (
        patch("app.api.routes.worker.worker_control.status", return_value=Running(False)),
        patch(
            "app.api.routes.worker.worker_status",
            return_value=WorkerStatus(
                name="worker",
                seen_at=datetime.now(timezone.utc),
                stale=False,
            ),
        ),
    ):
        res = api_client.post("/api/worker/start")
    assert res.status_code == 409
    assert "уже работает" in res.json()["detail"]


def test_stop_refuses_when_the_panel_did_not_start_it(api_client):
    with patch("app.api.routes.worker.worker_control.status", return_value=Running(False)):
        res = api_client.post("/api/worker/stop")
    assert res.status_code == 409


def test_start_reports_a_spawn_failure(api_client):
    with (
        patch("app.api.routes.worker.worker_control.status", return_value=Running(False)),
        patch(
            "app.api.routes.worker.worker_status",
            return_value=WorkerStatus(name="worker", seen_at=None, stale=True),
        ),
        patch(
            "app.api.routes.worker.worker_control.start",
            side_effect=WorkerProblem("не удалось запустить агента: no fork"),
        ),
    ):
        res = api_client.post("/api/worker/start")
    assert res.status_code == 409
    assert "не удалось запустить" in res.json()["detail"]


def test_lifespan_skips_spawn_when_heartbeat_is_alive(app_env, monkeypatch):
    from datetime import datetime, timezone

    from app.api import main as api_main
    from app.config import settings

    monkeypatch.setattr(settings, "worker_autostart", True, raising=True)
    fake_db = MagicMock()
    fake_db.close = MagicMock()
    monkeypatch.setattr(api_main, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        api_main,
        "worker_status",
        lambda _db: WorkerStatus(name="worker", seen_at=datetime.now(timezone.utc), stale=False),
    )
    with patch.object(api_main.worker_control, "ensure_started", return_value=None) as ensure:
        api_main._maybe_start_worker()
    ensure.assert_called_once_with(heartbeat_alive=True)


def test_lifespan_starts_worker_when_heartbeat_is_stale(app_env, monkeypatch):
    from app.api import main as api_main
    from app.config import settings

    monkeypatch.setattr(settings, "worker_autostart", True, raising=True)
    fake_db = MagicMock()
    fake_db.close = MagicMock()
    monkeypatch.setattr(api_main, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        api_main,
        "worker_status",
        lambda _db: WorkerStatus(name="worker", seen_at=None, stale=True),
    )
    with patch.object(
        api_main.worker_control, "ensure_started", return_value=Running(True, 77)
    ) as ensure:
        api_main._maybe_start_worker()
    ensure.assert_called_once_with(heartbeat_alive=False)
