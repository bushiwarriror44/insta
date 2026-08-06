"""Tests for app.accounts.session_manager.

These tests are the most critical regression net: the original bug was an
unconditional ``client.login()`` after ``load_settings``. The
``test_resume_with_valid_session_does_not_login`` test catches that.
"""
from __future__ import annotations

import json

import pytest
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    ClientError,
    LoginRequired,
    PleaseWaitFewMinutes,
    TwoFactorRequired,
)

from app.accounts.device_factory import generate_fingerprint
from app.accounts.session_manager import (
    AuthenticationError,
    HardCheckpoint,
    ProxyRequiredError,
    build_client,
    clear_session_file,
    login_or_resume,
    probe_session_auth,
    session_id_for_mobile_login,
    session_path,
)


@pytest.fixture()
def fingerprint(app_env):
    return generate_fingerprint("US")


def test_session_id_for_mobile_login_none_without_file(app_env):
    assert session_id_for_mobile_login("alice", "x" * 40) is None


def test_session_id_for_mobile_login_uses_db_sid_when_file_exists(app_env):
    _write_fake_session("alice", app_env)
    assert session_id_for_mobile_login("alice", "x" * 40) == "x" * 40


def _write_fake_session(username: str, app_env) -> None:
    path = session_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"saved": True}), encoding="utf-8")


def test_build_client_applies_settings_and_proxy_in_order(app_env, fake_client_class, fingerprint):
    client = build_client("alice", fingerprint, proxy_url="http://p:1")
    assert fake_client_class
    names = [c[0] for c in client.calls]
    expected_prefix = [
        "set_settings",
        "set_user_agent",
        "set_device",
        "set_locale",
        "set_country",
        "set_country_code",
        "set_timezone_offset",
        "set_proxy",
    ]
    assert names[: len(expected_prefix)] == expected_prefix


def test_build_client_without_proxy_is_rejected_before_network(app_env, fake_client_class, fingerprint):
    with pytest.raises(ProxyRequiredError):
        build_client("alice", fingerprint, proxy_url=None)
    assert fake_client_class == []


def test_login_or_resume_fresh_login_succeeds(app_env, fake_client_class, fingerprint):
    client = login_or_resume(
        username="alice",
        password="hunter2",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
    )
    names = [c[0] for c in client.calls]
    # Fresh login: no get_timeline_feed before login.
    assert names.index("login") < (names.index("get_timeline_feed") if "get_timeline_feed" in names else 999)
    assert client.last_login_args == ("alice", "hunter2")
    assert client.dumped_to is not None
    assert session_path("alice").exists()


def test_login_or_resume_without_proxy_fails_before_client_creation(
    app_env, fake_client_class, fingerprint
):
    with pytest.raises(ProxyRequiredError):
        login_or_resume(
            username="no-proxy",
            password="pw",
            fingerprint=fingerprint,
            proxy_url=None,
        )
    assert fake_client_class == []


def test_resume_with_valid_session_does_not_login(app_env, fake_client_class, fingerprint):
    """REGRESSION: this is the key bug fix from the original prototype.

    With a saved session and a working ``get_timeline_feed``, ``login``
    must not be called.
    """
    _write_fake_session("bob", app_env)

    client = login_or_resume(
        username="bob",
        password="pwd",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
    )
    names = [c[0] for c in client.calls]
    assert "get_timeline_feed" in names
    assert "login" not in names, "login() must not be called when session is valid"


def test_resume_with_login_required_falls_back_to_login(app_env, fake_client_class, fingerprint):
    _write_fake_session("carol", app_env)

    # Pre-create the client through build_client so we can configure timeline_exc
    # before login_or_resume runs; instead, hook into the factory:
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.timeline_exc = LoginRequired("login required")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        client = login_or_resume(
            username="carol",
            password="pwd",
            fingerprint=fingerprint,
            proxy_url="http://p:1",
        )
    finally:
        sm.Client = real_factory  # type: ignore[assignment]

    names = [c[0] for c in client.calls]
    all_names = [c[0] for inst in fake_client_class for c in inst.calls]
    assert "get_timeline_feed" in all_names
    assert "login" in names
    assert client.last_login_args == ("carol", "pwd")


def test_resume_with_challenge_required_raises_hard_checkpoint(app_env, fake_client_class, fingerprint):
    _write_fake_session("dave", app_env)
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.timeline_exc = ChallengeRequired("verify you")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(HardCheckpoint):
            login_or_resume("dave", "pwd", fingerprint, "http://p:1")
    finally:
        sm.Client = real_factory  # type: ignore[assignment]


def test_login_bad_password_raises_authentication_error(app_env, fake_client_class, fingerprint):
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.login_exc = BadPassword("nope")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(AuthenticationError) as excinfo:
            login_or_resume("eve", "wrong", fingerprint, "http://p:1")
        assert "bad password" in str(excinfo.value).lower()
    finally:
        sm.Client = real_factory  # type: ignore[assignment]


def test_login_two_factor_required_raises(app_env, fake_client_class, fingerprint):
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.login_exc = TwoFactorRequired("2fa")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(AuthenticationError):
            login_or_resume("frank", "pw", fingerprint, "http://p:1")
    finally:
        sm.Client = real_factory  # type: ignore[assignment]


def test_login_please_wait_raises_temporary(app_env, fake_client_class, fingerprint):
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.login_exc = PleaseWaitFewMinutes("slow down")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(AuthenticationError) as excinfo:
            login_or_resume("gina", "pw", fingerprint, "http://p:1")
        assert "rate" in str(excinfo.value).lower()
    finally:
        sm.Client = real_factory  # type: ignore[assignment]


def test_login_challenge_raises_hard_checkpoint(app_env, fake_client_class, fingerprint):
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.login_exc = ChallengeRequired("hard")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(HardCheckpoint):
            login_or_resume("hank", "pw", fingerprint, "http://p:1")
    finally:
        sm.Client = real_factory  # type: ignore[assignment]


def test_login_generic_client_error(app_env, fake_client_class, fingerprint):
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.login_exc = ClientError("oops")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(AuthenticationError):
            login_or_resume("ivy", "pw", fingerprint, "http://p:1")
    finally:
        sm.Client = real_factory  # type: ignore[assignment]


def test_login_with_verification_code_passes_through(app_env, fake_client_class, fingerprint):
    client = login_or_resume(
        username="jack",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        verification_code="123456",
    )
    assert client.last_login_kwargs == {"verification_code": "123456"}


def test_corrupt_session_file_treated_as_no_session(app_env, fake_client_class, fingerprint):
    path = session_path("kate")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("garbage", encoding="utf-8")
    client = login_or_resume("kate", "pw", fingerprint, "http://p:1")
    names = [c[0] for c in client.calls]
    assert "login" in names


def test_ensure_fingerprint_and_proxy_persists(app_env):
    from app.accounts.session_manager import ensure_fingerprint_and_proxy

    fp = ensure_fingerprint_and_proxy("liz", country="DE")
    assert fp.country == "DE"
    second = ensure_fingerprint_and_proxy("liz", country="DE")
    assert second.settings["uuids"]["uuid"] == fp.settings["uuids"]["uuid"]


def test_login_with_totp_seed_injects_code(app_env, fake_client_class, fingerprint):
    """A bare ``totp_seed`` should be expanded into a 6-digit verification_code
    via :mod:`pyotp` and forwarded to ``client.login``."""
    client = login_or_resume(
        username="mia",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        totp_seed="JBSWY3DPEHPK3PXP",
    )
    code = client.last_login_kwargs.get("verification_code")
    assert code is not None
    assert code.isdigit() and len(code) == 6


def test_login_two_factor_required_without_totp_still_raises(
    app_env, fake_client_class, fingerprint, monkeypatch
):
    """Without a totp_seed *and* without an explicit verification_code,
    a TwoFactorRequired must surface as an AuthenticationError just like
    before — anti-detection changes must not silently swallow this case."""
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.login_exc = TwoFactorRequired("send 2fa")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(AuthenticationError):
            login_or_resume("nora", "pw", fingerprint, "http://p:1")
    finally:
        sm.Client = real_factory  # type: ignore[assignment]


def test_invalid_totp_seed_does_not_crash(app_env, fake_client_class, fingerprint):
    """A garbage totp_seed should fall through to plain login() rather than
    raising — operators should still be able to manually solve 2FA."""
    client = login_or_resume(
        username="opal",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        totp_seed="not-a-real-seed",
    )
    # No code generated → login was called without a verification_code.
    assert client.last_login_kwargs.get("verification_code") in (None, "")


def test_maybe_rotate_session_uuids_no_rotation_under_threshold(app_env):
    """Within the rotation cadence (3-7 days), the function must be a no-op."""
    from datetime import datetime, timedelta, timezone

    from app.accounts.device_factory import generate_fingerprint
    from app.accounts.session_manager import maybe_rotate_session_uuids

    fp = generate_fingerprint("US")
    original = fp.settings["uuids"]["client_session_id"]
    rotated, _ = maybe_rotate_session_uuids(
        "user1", fp, datetime.now(timezone.utc) - timedelta(hours=4)
    )
    assert rotated is False
    assert fp.settings["uuids"]["client_session_id"] == original


def test_maybe_rotate_session_uuids_rotates_after_window(app_env):
    """After 8+ days the session ids must rotate, hardware ids stay put."""
    from datetime import datetime, timedelta, timezone

    from app.accounts.device_factory import generate_fingerprint
    from app.accounts.session_manager import maybe_rotate_session_uuids

    fp = generate_fingerprint("US")
    before = dict(fp.settings["uuids"])
    rotated, _ = maybe_rotate_session_uuids(
        "user2", fp, datetime.now(timezone.utc) - timedelta(days=10)
    )
    after = fp.settings["uuids"]
    assert rotated is True
    assert after["client_session_id"] != before["client_session_id"]
    assert after["pigeon_session_id"] != before["pigeon_session_id"]
    # Hardware ids must NOT change on session rotation.
    assert after["device_id"] == before["device_id"]
    assert after["phone_id"] == before["phone_id"]
    assert after["uuid"] == before["uuid"]


VALID_SESSION_ID = "a" * 40


def _patch_client_username(monkeypatch_or_sm, username: str):
    """Set FakeInstagrapiClient.account_info_username to match *username*."""
    import app.accounts.session_manager as sm

    real_factory = sm.Client

    def _factory(*args, **kwargs):
        c = real_factory(*args, **kwargs)
        c.account_info_username = username
        return c

    sm.Client = _factory  # type: ignore[assignment]
    return sm, real_factory


def test_login_via_session_id_when_no_saved_session(app_env, fake_client_class, fingerprint):
    sm, real = _patch_client_username(None, "sid")
    try:
        client = login_or_resume(
            username="sid",
            password="pw",
            fingerprint=fingerprint,
            proxy_url="http://p:1",
            session_id=VALID_SESSION_ID,
        )
    finally:
        sm.Client = real  # type: ignore[assignment]

    names = [c[0] for c in client.calls]
    assert "login_by_sessionid" in names
    assert "login" not in names
    assert client.last_sessionid == VALID_SESSION_ID
    assert client.dumped_to is not None


def test_session_id_rejected_falls_back_to_password_login(
    app_env, fake_client_class, fingerprint
):
    sm, real = _patch_client_username(None, "sid2")

    def _factory(*args, **kwargs):
        c = real(*args, **kwargs)
        c.account_info_username = "sid2"
        c.sessionid_exc = ClientError("invalid sessionid")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        client = login_or_resume(
            username="sid2",
            password="pw",
            fingerprint=fingerprint,
            proxy_url="http://p:1",
            session_id=VALID_SESSION_ID,
        )
    finally:
        sm.Client = real  # type: ignore[assignment]

    names = [c[0] for c in client.calls]
    all_names = [c[0] for inst in fake_client_class for c in inst.calls]
    assert "login_by_sessionid" in all_names
    assert "login" in names


def test_session_id_takes_priority_over_valid_session_file(
    app_env, fake_client_class, fingerprint
):
    _write_fake_session("prio", app_env)
    sm, real = _patch_client_username(None, "prio")
    try:
        client = login_or_resume(
            username="prio",
            password="pw",
            fingerprint=fingerprint,
            proxy_url="http://p:1",
            session_id=VALID_SESSION_ID,
        )
    finally:
        sm.Client = real  # type: ignore[assignment]

    names = [c[0] for c in client.calls]
    assert names.index("login_by_sessionid") < names.index("get_timeline_feed")
    assert "login" not in names


def test_session_id_username_mismatch_raises(app_env, fake_client_class, fingerprint):
    sm, real = _patch_client_username(None, "bob")
    try:
        with pytest.raises(AuthenticationError) as excinfo:
            login_or_resume(
                username="alice",
                password="pw",
                fingerprint=fingerprint,
                proxy_url="http://p:1",
                session_id=VALID_SESSION_ID,
            )
        assert "bob" in str(excinfo.value).lower()
    finally:
        sm.Client = real  # type: ignore[assignment]


def test_clear_session_file_removes_disk_session(app_env):
    path = session_path("wipe")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert clear_session_file("wipe") is True
    assert not path.exists()
    assert clear_session_file("wipe") is False


def test_session_id_used_after_expired_saved_session(
    app_env, fake_client_class, fingerprint
):
    _write_fake_session("sid3", app_env)
    sm, real = _patch_client_username(None, "sid3")

    def _factory(*args, **kwargs):
        c = real(*args, **kwargs)
        c.account_info_username = "sid3"
        c.sessionid_exc = ClientError("bad cookie")
        state = {"calls": 0}

        def _timeline():
            c._record("get_timeline_feed")
            state["calls"] += 1
            if state["calls"] == 1:
                raise LoginRequired("expired")
            return c.timeline_response

        c.get_timeline_feed = _timeline
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        client = login_or_resume(
            username="sid3",
            password="pw",
            fingerprint=fingerprint,
            proxy_url="http://p:1",
            session_id=VALID_SESSION_ID,
        )
    finally:
        sm.Client = real  # type: ignore[assignment]

    names = [c[0] for c in client.calls]
    all_names = [c[0] for inst in fake_client_class for c in inst.calls]
    assert "login_by_sessionid" in all_names
    assert "login" in names


def test_backup_code_strips_spaces(app_env, fake_client_class, fingerprint):
    client = login_or_resume(
        username="backup",
        password="pw",
        fingerprint=fingerprint,
        proxy_url="http://p:1",
        verification_code="12 34 56 78",
    )
    assert client.last_login_kwargs == {"verification_code": "12345678"}


def test_probe_falls_through_to_session_file_when_db_sid_invalid(
    app_env, fake_client_class, fingerprint
):
    _write_fake_session("probefile", app_env)
    import app.accounts.session_manager as sm

    real = sm.Client
    diag_lines: list[tuple[str, str, str]] = []

    def _factory(*args, **kwargs):
        c = real(*args, **kwargs)
        c.account_info_username = "probefile"
        c.sessionid_exc = ClientError("invalid sessionid")
        return c

    sm.Client = _factory  # type: ignore[assignment]
    try:
        result = probe_session_auth(
            "probefile",
            fingerprint,
            "http://p:1",
            session_id=VALID_SESSION_ID,
            diag=lambda level, step, msg: diag_lines.append((level, step, msg)),
        )
    finally:
        sm.Client = real  # type: ignore[assignment]

    assert result.ok is True
    assert result.method == "session_file"
    joined = " | ".join(m for _, _, m in diag_lines)
    assert "пробуем session_*.json" in joined
    assert "session_file OK" in joined
    assert any("elapsed_ms=" in m for _, _, m in diag_lines)
