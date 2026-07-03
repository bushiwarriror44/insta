"""Shared pytest fixtures for the test suite.

Test isolation strategy:
    1. BEFORE any ``app.*`` import we point ``DATA_DIR`` and friends at a
       session-level temp directory via ``os.environ``. This ensures the
       module-level constants (e.g. ``app.accounts.challenge.CHALLENGES_DIR``)
       are computed against safe paths, not the repo's ``data/``.
    2. Per test, the ``app_env`` fixture moves all settings paths to the
       test's ``tmp_path`` and recreates the SQLAlchemy engine + SessionLocal
       against an isolated SQLite file, monkeypatching every module that
       captured a reference at import time.
    3. The ``fake_instagrapi_client`` fixture provides a class compatible
       with everything the production code calls on the real ``Client``.
    4. The ``fake_subprocess`` fixture replaces ``subprocess.run`` /
       ``subprocess.check_output`` inside ``app.video.uniquifier`` with
       deterministic stubs.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# --- 1. Pre-import environment setup ---------------------------------------
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="reels_test_root_"))
os.environ.setdefault("DATA_DIR", str(_TEST_ROOT))
os.environ.setdefault("SESSIONS_DIR", str(_TEST_ROOT / "sessions"))
os.environ.setdefault("DEVICES_DIR", str(_TEST_ROOT / "devices"))
os.environ.setdefault("PLAYWRIGHT_DIR", str(_TEST_ROOT / "playwright"))
os.environ.setdefault("VIDEO_SOURCE_DIR", str(_TEST_ROOT / "videos" / "source"))
os.environ.setdefault("VIDEO_OUT_DIR", str(_TEST_ROOT / "videos" / "out"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_ROOT / 'init.db'}")
os.environ.setdefault("LOG_FILE", str(_TEST_ROOT / "app.log"))
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("PROXY_HEALTH_URL", "https://api.ipify.org?format=json")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")

# Ensure the project root is importable regardless of how pytest is invoked.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- 2. Now safe to import app ---------------------------------------------
import pytest  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models import Base  # noqa: E402
import app.db as app_db  # noqa: E402
import app.db.session as app_db_session  # noqa: E402


@pytest.fixture()
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test path + DB isolation.

    Yields an object with ``.SessionLocal`` (callable producing a fresh
    Session) and ``.tmp_path`` for convenience.
    """
    sessions = tmp_path / "sessions"
    devices = tmp_path / "devices"
    playwright_dir = tmp_path / "playwright"
    src = tmp_path / "videos" / "source"
    out = tmp_path / "videos" / "out"
    challenges = tmp_path / "challenges"
    for d in (sessions, devices, playwright_dir, src, out, challenges):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=True)
    monkeypatch.setattr(settings, "sessions_dir", sessions, raising=True)
    monkeypatch.setattr(settings, "devices_dir", devices, raising=True)
    monkeypatch.setattr(settings, "playwright_dir", playwright_dir, raising=True)
    monkeypatch.setattr(settings, "video_source_dir", src, raising=True)
    monkeypatch.setattr(settings, "video_out_dir", out, raising=True)
    monkeypatch.setattr(settings, "log_file", tmp_path / "app.log", raising=True)

    db_file = tmp_path / "test.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setattr(settings, "database_url", db_url, raising=True)

    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        future=True,
    )

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):  # noqa: WPS430
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(app_db_session, "engine", engine, raising=True)
    monkeypatch.setattr(app_db_session, "SessionLocal", SessionLocal, raising=True)
    monkeypatch.setattr(app_db, "engine", engine, raising=True)
    monkeypatch.setattr(app_db, "SessionLocal", SessionLocal, raising=True)

    # Modules that captured ``SessionLocal`` at import time need patching too.
    for module_name in ("app.alerts.telegram", "app.scheduler.worker", "app.cli"):
        if module_name in sys.modules:
            mod = sys.modules[module_name]
            if hasattr(mod, "SessionLocal"):
                monkeypatch.setattr(mod, "SessionLocal", SessionLocal, raising=True)

    # CHALLENGES_DIR is computed at module import time from settings.data_dir.
    if "app.accounts.challenge" in sys.modules:
        monkeypatch.setattr(
            sys.modules["app.accounts.challenge"], "CHALLENGES_DIR", challenges, raising=True
        )

    class _Env:
        pass

    env = _Env()
    env.tmp_path = tmp_path
    env.SessionLocal = SessionLocal
    env.engine = engine
    env.sessions_dir = sessions
    env.devices_dir = devices
    env.challenges_dir = challenges
    env.video_source_dir = src
    env.video_out_dir = out
    yield env

    engine.dispose()


@pytest.fixture()
def db_session(app_env):
    session = app_env.SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --- Sample factories -------------------------------------------------------


@pytest.fixture()
def make_proxy(db_session):
    """Factory: create a Proxy row and return it. Default label is auto-incrementing."""
    from app.db import Proxy

    counter = {"i": 0}

    def _make(label: str | None = None, url: str = "http://u:p@host:8000", country: str = "US",
              timezone: str = "UTC", is_healthy: bool = True) -> Proxy:
        if label is None:
            counter["i"] += 1
            label = f"proxy-{counter['i']}"
        proxy = Proxy(label=label, url=url, country=country, timezone=timezone, is_healthy=is_healthy)
        db_session.add(proxy)
        db_session.commit()
        db_session.refresh(proxy)
        return proxy

    return _make


@pytest.fixture()
def make_account(db_session, make_proxy):
    """Factory: create an Account bound to a Proxy."""
    from app.db import Account, AccountStatus

    def _make(
        username: str = "tester",
        password: str = "secret",
        proxy=None,
        timezone: str = "UTC",
        status: AccountStatus = AccountStatus.active,
        daily_post_cap: int = 3,
        min_gap_hours: float = 4.0,
        active_hour_start: int = 10,
        active_hour_end: int = 22,
    ):
        proxy = proxy or make_proxy()
        account = Account(
            username=username,
            password=password,
            proxy_id=proxy.id,
            timezone=timezone,
            status=status,
            daily_post_cap=daily_post_cap,
            min_gap_hours=min_gap_hours,
            active_hour_start=active_hour_start,
            active_hour_end=active_hour_end,
        )
        db_session.add(account)
        db_session.commit()
        db_session.refresh(account)
        return account

    return _make


# --- Fake instagrapi.Client -------------------------------------------------


class FakeFeedItem:
    def __init__(self, pk: int, has_liked: bool = False):
        self.pk = pk
        self.has_liked = has_liked


class FakeMedia:
    def __init__(self, pk: str = "1234567890_1", code: str = "ABCxyz"):
        self.pk = pk
        self.code = code


class FakeTrayItem:
    def __init__(self, pk: int):
        self.pk = pk
        self.id = pk
        self.user = pk


class FakeReelsTray:
    def __init__(self, items: list[FakeTrayItem] | None = None):
        self.tray = items or [FakeTrayItem(1001)]


class FakeInstagrapiClient:
    """Mimics the surface of ``instagrapi.Client`` used across the app."""

    def __init__(self, *, request_timeout: int = 30):
        self.request_timeout = request_timeout
        self.calls: list[tuple[str, tuple, dict]] = []
        self.settings_payload: dict | None = None
        self.user_agent: str | None = None
        self.device: dict | None = None
        self.locale: str | None = None
        self.country: str | None = None
        self.country_code: int | None = None
        self.timezone_offset: int | None = None
        self.proxy_url: str | None = None
        self.challenge_code_handler = None
        self.dumped_to: str | None = None
        self.user_id: int = 999000
        # Configurable behavior, set on instances:
        self.timeline_exc: Exception | None = None
        self.login_exc: Exception | None = None
        self.sessionid_exc: Exception | None = None
        self.clip_upload_exc: Exception | None = None
        self.media_like_exc: Exception | None = None
        self.media_info_exc: Exception | None = None
        self.last_login_args: tuple = ()
        self.last_login_kwargs: dict = {}
        self.last_sessionid: str | None = None
        self.timeline_response: dict = {"feed_items": [FakeFeedItem(pk=1, has_liked=False)]}
        self.reels_tray_response = FakeReelsTray()
        self.user_stories_response: list = [object()]
        self.account_info_response = type("AccountInfo", (), {"username": "testuser"})()
        self.account_info_username: str = "testuser"
        self.upload_result = FakeMedia()
        self.media_info_response = {
            "pk": "1234567890_1",
            "code": "ABCxyz",
            "view_count": 100,
            "play_count": 120,
            "like_count": 7,
            "comment_count": 2,
            "save_count": 1,
            "share_count": 3,
        }
        self.media_info_v2_response = {
            "pk": "1234567890_1",
            "code": "ABCxyz",
            "view_count": 50,
            "play_count": 60,
            "like_count": 3,
            "comment_count": 1,
            "save_count": 0,
            "share_count": 1,
        }
        self.user_info_v1_response = {"pk": self.user_id}

    def _record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))

    def set_settings(self, payload: dict) -> None:
        self._record("set_settings", payload)
        self.settings_payload = payload

    def set_user_agent(self, ua: str) -> None:
        self._record("set_user_agent", ua)
        self.user_agent = ua

    def set_device(self, device: dict) -> None:
        self._record("set_device", device)
        self.device = device

    def set_locale(self, locale: str) -> None:
        self._record("set_locale", locale)
        self.locale = locale

    def set_country(self, country: str) -> None:
        self._record("set_country", country)
        self.country = country

    def set_country_code(self, code: int) -> None:
        self._record("set_country_code", code)
        self.country_code = code

    def set_timezone_offset(self, offset: int) -> None:
        self._record("set_timezone_offset", offset)
        self.timezone_offset = offset

    def set_proxy(self, url: str) -> None:
        self._record("set_proxy", url)
        self.proxy_url = url

    def get_timeline_feed(self):
        self._record("get_timeline_feed")
        if self.timeline_exc is not None:
            raise self.timeline_exc
        return self.timeline_response

    def login(self, username: str, password: str, verification_code: str | None = None):
        self._record("login", username, password, verification_code=verification_code)
        self.last_login_args = (username, password)
        self.last_login_kwargs = {"verification_code": verification_code}
        if self.login_exc is not None:
            raise self.login_exc
        return True

    def login_by_sessionid(self, session_id: str):
        self._record("login_by_sessionid", session_id)
        self.last_sessionid = session_id
        if self.sessionid_exc is not None:
            raise self.sessionid_exc
        return True

    def dump_settings(self, path: str) -> None:
        self._record("dump_settings", path)
        self.dumped_to = path
        Path(path).write_text(json.dumps({"dumped": True}), encoding="utf-8")

    def clip_upload(self, path: str, caption: str = ""):
        self._record("clip_upload", path, caption=caption)
        if self.clip_upload_exc is not None:
            raise self.clip_upload_exc
        return self.upload_result

    def photo_upload(self, path: str, caption: str = ""):
        self._record("photo_upload", path, caption=caption)
        return self.upload_result

    def video_upload(self, path: str, caption: str = ""):
        self._record("video_upload", path, caption=caption)
        return self.upload_result

    def media_info(self, media_id):
        self._record("media_info", media_id)
        if self.media_info_exc is not None:
            raise self.media_info_exc
        return self.media_info_response

    def media_info_v2(self, media_id):
        self._record("media_info_v2", media_id)
        return self.media_info_v2_response

    def media_like(self, media_pk):
        self._record("media_like", media_pk)
        if self.media_like_exc is not None:
            raise self.media_like_exc
        return True

    def reels_tray(self):
        self._record("reels_tray")
        return self.reels_tray_response

    def user_stories(self, user_id: int):
        self._record("user_stories", user_id)
        return self.user_stories_response

    def account_info(self):
        self._record("account_info")
        uname = self.account_info_username
        return type("AccountInfo", (), {"username": uname})()

    def user_info_v1(self, user_id):
        self._record("user_info_v1", user_id)
        return self.user_info_v1_response

    def direct_threads(self, amount: int = 5):
        self._record("direct_threads", amount=amount)
        return []

    def news_inbox_v1(self):
        self._record("news_inbox_v1")
        return {}

    def explore_page(self):
        self._record("explore_page")
        return {}

    def media_seen(self, payload):
        self._record("media_seen", payload)
        return True

    def story_seen(self, payload):
        self._record("story_seen", payload)
        return True


@pytest.fixture()
def fake_client_class(monkeypatch):
    """Replace ``instagrapi.Client`` inside ``app.accounts.session_manager``."""
    instances: list[FakeInstagrapiClient] = []

    def _factory(*args, **kwargs):
        client = FakeInstagrapiClient(*args, **kwargs)
        instances.append(client)
        return client

    import app.accounts.session_manager as sm

    monkeypatch.setattr(sm, "Client", _factory, raising=True)
    return instances


# --- Subprocess fixture for uniquifier --------------------------------------


@pytest.fixture()
def fake_subprocess(monkeypatch):
    """Capture ffmpeg/ffprobe calls; return canned ffprobe output."""
    captured: dict[str, list[list[str]]] = {"run": [], "check_output": []}

    probe_payload = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "30/1",
            },
            {"codec_type": "audio"},
        ],
        "format": {"duration": "5.0"},
    }
    state = {"probe_payload": probe_payload, "run_returncode": 0, "run_stderr": b""}

    def _check_output(cmd, stderr=None, **_kwargs):
        captured["check_output"].append(list(cmd))
        return json.dumps(state["probe_payload"]).encode("utf-8")

    class _CompletedProcess:
        def __init__(self, returncode: int = 0, stderr: bytes = b""):
            self.returncode = returncode
            self.stderr = stderr

    def _run(cmd, check=False, stdout=None, stderr=None, **_kwargs):
        captured["run"].append(list(cmd))
        if state["run_returncode"] != 0:
            import subprocess as _sp

            raise _sp.CalledProcessError(
                state["run_returncode"], cmd, output=b"", stderr=state["run_stderr"]
            )
        # The real ffmpeg writes the output file at cmd[-1]. Emulate that so the
        # subsequent ``dst.stat()`` call in ``uniquify`` doesn't blow up.
        from pathlib import Path as _Path

        try:
            out_path = _Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"\x00" * 64)
        except (OSError, IndexError):
            pass
        return _CompletedProcess(0, b"")

    import app.video.uniquifier as un

    monkeypatch.setattr(un.subprocess, "check_output", _check_output, raising=True)
    monkeypatch.setattr(un.subprocess, "run", _run, raising=True)
    monkeypatch.setattr(un, "ffmpeg_bin", lambda: "ffmpeg-fake.exe", raising=True)
    monkeypatch.setattr(un, "ffprobe_bin", lambda: "ffprobe-fake.exe", raising=True)

    captured["state"] = state
    return captured


# --- Misc helpers -----------------------------------------------------------


@pytest.fixture()
def fast_sleep(monkeypatch):
    """Make ``time.sleep`` a no-op everywhere it is imported via ``time``."""
    import time

    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None, raising=True)
    return time


@pytest.fixture()
def reset_logging(monkeypatch):
    """Reset the ``configure_logging`` once-flag between tests."""
    import app.logging_setup as ls

    monkeypatch.setattr(ls, "_CONFIGURED", False, raising=True)
    return ls
