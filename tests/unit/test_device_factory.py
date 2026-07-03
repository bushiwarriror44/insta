"""Tests for app.accounts.device_factory."""
from __future__ import annotations

import re

from app.accounts.device_factory import (
    DeviceFingerprint,
    device_path,
    generate_fingerprint,
    get_or_create_fingerprint,
    load_fingerprint,
    save_fingerprint,
)

UA_RE = re.compile(r"^Instagram \S+ Android \(\d+/\S+;.*\)$")


def test_generate_fingerprint_basic_shape(app_env):
    fp = generate_fingerprint("US")
    assert fp.country == "US"
    assert fp.country_code == 1
    assert fp.locale.endswith("_US")
    assert UA_RE.match(fp.user_agent), fp.user_agent
    assert "uuids" in fp.settings
    uuids = fp.settings["uuids"]
    for key in ("phone_id", "uuid", "client_session_id", "advertising_id", "device_id"):
        assert uuids[key]


def test_generate_fingerprint_country_fallback(app_env):
    fp = generate_fingerprint("ZZ")
    # Unknown country falls back to US country_code=1.
    assert fp.country_code == 1


def test_generate_fingerprint_uuids_unique(app_env):
    a = generate_fingerprint("US")
    b = generate_fingerprint("US")
    assert a.settings["uuids"]["uuid"] != b.settings["uuids"]["uuid"]
    assert a.settings["uuids"]["device_id"] != b.settings["uuids"]["device_id"]


def test_save_and_load_round_trip(app_env):
    fp = generate_fingerprint("DE")
    save_fingerprint("alice", fp)
    assert device_path("alice").exists()
    loaded = load_fingerprint("alice")
    assert loaded is not None
    assert loaded.country == fp.country
    assert loaded.user_agent == fp.user_agent
    assert loaded.settings["uuids"]["uuid"] == fp.settings["uuids"]["uuid"]


def test_load_fingerprint_returns_none_when_missing(app_env):
    assert load_fingerprint("nobody") is None


def test_load_fingerprint_returns_none_on_corrupt(app_env):
    path = device_path("broken")
    path.write_text("{ this is not valid json", encoding="utf-8")
    assert load_fingerprint("broken") is None


def test_get_or_create_idempotent(app_env):
    first = get_or_create_fingerprint("bob", country="GB")
    second = get_or_create_fingerprint("bob", country="GB")
    assert first.settings["uuids"]["uuid"] == second.settings["uuids"]["uuid"]
    assert second.country == "GB"


def test_fingerprint_to_dict_round_trip():
    fp = DeviceFingerprint(
        settings={"uuids": {}, "device_settings": {"model": "X"}},
        user_agent="UA",
        locale="en_US",
        country="US",
        country_code=1,
        timezone_offset=0,
    )
    restored = DeviceFingerprint.from_dict(fp.to_dict())
    assert restored.user_agent == "UA"
    assert restored.country == "US"


def test_family_device_id_present(app_env):
    """family_device_id is part of every fingerprint we generate; missing
    field would mean Instagram sees a brand-new Meta device on every login."""
    fp = generate_fingerprint("US")
    uuids = fp.settings["uuids"]
    assert uuids.get("family_device_id"), "family_device_id should be present"
    assert uuids["family_device_id"].startswith("android-")


def test_load_app_versions_from_file_parses(tmp_path):
    import json

    from app.accounts.device_factory import (
        load_app_versions_from_file,
        set_app_versions,
        _APP_VERSIONS,
    )

    payload = [
        {"version": "390.1.0.39.92", "code": "682104221"},
        {"version": "391.0.0.40.00", "code": "682500000"},
    ]
    file = tmp_path / "av.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    parsed = load_app_versions_from_file(file)
    assert ("390.1.0.39.92", "682104221") in parsed
    set_app_versions(parsed)
    # The pool length must reflect the freshly loaded set.
    from app.accounts import device_factory as df

    assert len(df._APP_VERSIONS) == 2


def test_load_app_versions_rejects_empty(tmp_path):
    import json

    from app.accounts.device_factory import load_app_versions_from_file

    file = tmp_path / "empty.json"
    file.write_text(json.dumps([]), encoding="utf-8")
    import pytest as _pt
    with _pt.raises(ValueError):
        load_app_versions_from_file(file)


def test_rotate_session_uuids_changes_only_session_ids(app_env):
    from app.accounts.device_factory import rotate_session_uuids

    fp = generate_fingerprint("US")
    before = dict(fp.settings["uuids"])
    rotate_session_uuids(fp)
    after = fp.settings["uuids"]
    assert after["client_session_id"] != before["client_session_id"]
    assert after["pigeon_session_id"] != before["pigeon_session_id"]
    assert after["device_id"] == before["device_id"]
    assert after["phone_id"] == before["phone_id"]
    assert after["uuid"] == before["uuid"]
    assert after["family_device_id"] == before["family_device_id"]
