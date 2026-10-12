"""Per-account Android device fingerprint factory.

Each Instagram account is assigned ONE device permanently. The fingerprint
includes hardware specs, UUIDs, locale/country/timezone aligned with the
proxy geo. Once generated, it must NEVER change — switching the device
fingerprint of an existing session is one of the strongest detection
signals on the platform.

The fingerprint is persisted both on disk (``data/devices/<username>.json``)
and in the DB ``devices`` table. The disk copy is used as the source of
truth and re-fed into instagrapi via ``client.set_settings``.
"""
from __future__ import annotations

import json
import random
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.logging_setup import get_logger

logger = get_logger(__name__)


# A curated set of realistic Android devices. The pool is wide enough that the
# fingerprint distribution across our account portfolio looks like a sample of
# real-world devices, not a single hardware SKU.
# (manufacturer, model, codename, android_version, android_release, dpi, resolution, chipset)
_DEVICE_POOL: list[tuple[str, str, str, int, str, str, str, str]] = [
    # Samsung Galaxy S/A 2021–2024
    ("samsung", "SM-G991B", "o1s", 33, "13", "420dpi", "1080x2340", "exynos2100"),
    ("samsung", "SM-G998B", "p3s", 33, "13", "515dpi", "1440x3088", "exynos2100"),
    ("samsung", "SM-S908B", "b0s", 33, "13", "500dpi", "1440x3088", "snapdragon8gen1"),
    ("samsung", "SM-A536B", "a53x", 33, "13", "450dpi", "1080x2400", "exynos1280"),
    ("samsung", "SM-A546B", "a54x", 34, "14", "450dpi", "1080x2340", "exynos1380"),
    ("samsung", "SM-S918B", "dm3q", 34, "14", "510dpi", "1440x3088", "snapdragon8gen2"),
    ("samsung", "SM-S928B", "e3q", 34, "14", "505dpi", "1440x3120", "snapdragon8gen3"),
    ("samsung", "SM-S921B", "e1q", 34, "14", "450dpi", "1080x2340", "snapdragon8gen3"),
    ("samsung", "SM-F946B", "q5q", 34, "14", "420dpi", "1812x2176", "snapdragon8gen2"),
    ("samsung", "SM-A346E", "a34x", 33, "13", "440dpi", "1080x2340", "dimensity1080"),
    # Xiaomi 12/13/14, Redmi Note
    ("xiaomi", "2201123G", "cupid", 33, "13", "440dpi", "1080x2400", "snapdragon8gen1"),
    ("xiaomi", "2210132G", "fuxi", 33, "13", "480dpi", "1440x3200", "snapdragon8gen2"),
    ("xiaomi", "23049PCD8G", "diting", 34, "14", "440dpi", "1080x2400", "dimensity7200u"),
    ("xiaomi", "23116PN5BG", "shennong", 34, "14", "480dpi", "1200x2670", "snapdragon8gen3"),
    ("xiaomi", "23117RA68G", "aurora", 34, "14", "440dpi", "1220x2712", "snapdragon8gen3"),
    ("xiaomi", "2312DRA50G", "garnet", 34, "14", "395dpi", "1080x2400", "snapdragon4gen2"),
    # OnePlus / Realme
    ("OnePlus", "CPH2449", "salami", 33, "13", "450dpi", "1080x2412", "snapdragon8gen2"),
    ("OnePlus", "CPH2415", "waffle", 33, "13", "450dpi", "1080x2412", "snapdragon8plus"),
    ("OnePlus", "CPH2581", "aston", 34, "14", "480dpi", "1440x3168", "snapdragon8gen3"),
    ("realme", "RMX3771", "pioneer", 33, "13", "440dpi", "1080x2412", "snapdragon8gen2"),
    # Google Pixel 7/8/8 Pro
    ("google", "Pixel 7", "panther", 33, "13", "420dpi", "1080x2400", "tensor2"),
    ("google", "Pixel 7 Pro", "cheetah", 34, "14", "560dpi", "1440x3120", "tensor2"),
    ("google", "Pixel 8", "shiba", 34, "14", "420dpi", "1080x2400", "tensor3"),
    ("google", "Pixel 8 Pro", "husky", 34, "14", "490dpi", "1344x2992", "tensor3"),
    ("google", "Pixel 8a", "akita", 34, "14", "420dpi", "1080x2400", "tensor3"),
    # Honor / Nothing
    ("HONOR", "ALI-NX1", "ali", 34, "14", "460dpi", "1224x2700", "snapdragon8gen3"),
    ("HONOR", "MGI-NX1", "magic5", 33, "13", "460dpi", "1224x2700", "snapdragon8gen2"),
    ("Nothing", "A065", "Pacman", 33, "13", "395dpi", "1080x2412", "snapdragon8plus"),
    ("Nothing", "A142", "Pong", 34, "14", "395dpi", "1084x2412", "snapdragon8sgen3"),
    # Motorola
    ("motorola", "moto g84 5G", "fogos", 33, "13", "395dpi", "1080x2400", "snapdragon695"),
    ("motorola", "edge 50 fusion", "fogon", 34, "14", "395dpi", "1080x2400", "snapdragon7sgen2"),
]

# Locale-country-timezone triplets. Pick by proxy country.
_GEO_PROFILES: dict[str, dict[str, Any]] = {
    "US": {"locales": ["en_US"], "country_code": 1, "timezone_offsets": [-28800, -25200, -21600, -18000]},
    "GB": {"locales": ["en_GB"], "country_code": 44, "timezone_offsets": [0, 3600]},
    "DE": {"locales": ["de_DE"], "country_code": 49, "timezone_offsets": [3600, 7200]},
    "FR": {"locales": ["fr_FR"], "country_code": 33, "timezone_offsets": [3600, 7200]},
    "ES": {"locales": ["es_ES"], "country_code": 34, "timezone_offsets": [3600, 7200]},
    "IT": {"locales": ["it_IT"], "country_code": 39, "timezone_offsets": [3600, 7200]},
    "PL": {"locales": ["pl_PL"], "country_code": 48, "timezone_offsets": [3600, 7200]},
    "NL": {"locales": ["nl_NL"], "country_code": 31, "timezone_offsets": [3600, 7200]},
    "BR": {"locales": ["pt_BR"], "country_code": 55, "timezone_offsets": [-10800, -14400]},
    "MX": {"locales": ["es_MX"], "country_code": 52, "timezone_offsets": [-21600, -25200]},
    "TR": {"locales": ["tr_TR"], "country_code": 90, "timezone_offsets": [10800]},
    "AE": {"locales": ["ar_AE", "en_AE"], "country_code": 971, "timezone_offsets": [14400]},
    "IN": {"locales": ["en_IN", "hi_IN"], "country_code": 91, "timezone_offsets": [19800]},
    "ID": {"locales": ["id_ID"], "country_code": 62, "timezone_offsets": [25200, 28800]},
    "TH": {"locales": ["th_TH"], "country_code": 66, "timezone_offsets": [25200]},
    "JP": {"locales": ["ja_JP"], "country_code": 81, "timezone_offsets": [32400]},
    "RU": {"locales": ["ru_RU"], "country_code": 7, "timezone_offsets": [10800]},
    "UA": {"locales": ["uk_UA"], "country_code": 380, "timezone_offsets": [7200]},
    "KZ": {"locales": ["ru_KZ", "kk_KZ"], "country_code": 7, "timezone_offsets": [18000]},
    "AM": {"locales": ["hy_AM", "en_AM"], "country_code": 374, "timezone_offsets": [14400]},
}


# Recent stable Instagram Android app versions. Override at runtime by
# editing ``data/app_versions.json`` and calling
# ``python -m app.cli refresh-app-versions`` (the CLI updates this list in
# memory for the running process and validates the structure on disk).
_APP_VERSIONS: list[tuple[str, str]] = [
    ("428.0.0.47.67", "961145276"),
    ("446.0.0.49.77", "385211303"),
    ("448.0.0.0.20", "1065560286"),
]


def load_app_versions_from_file(path: Path) -> list[tuple[str, str]]:
    """Read ``[{"version": "...", "code": "..."}, ...]`` from a JSON file.

    The CLI uses this so operators can refresh app versions without
    redeploying — Instagram bumps its Android app every 1–2 weeks and a
    stale ``_APP_VERSIONS`` is one of the cheapest signals to forge.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("app_versions.json должен содержать список верхнего уровня")
    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        version = str(item.get("version", "")).strip()
        code = str(item.get("code", "")).strip()
        if version and code:
            out.append((version, code))
    if not out:
        raise ValueError("app_versions.json не содержит пригодных записей")
    return out


def set_app_versions(values: list[tuple[str, str]]) -> None:
    """Replace the in-memory app versions pool. Used by the refresh CLI."""
    global _APP_VERSIONS
    _APP_VERSIONS = list(values)


@dataclass
class DeviceFingerprint:
    settings: dict[str, Any] = field(default_factory=dict)
    user_agent: str = ""
    locale: str = "en_US"
    country: str = "US"
    country_code: int = 1
    timezone_offset: int = -25200

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "user_agent": self.user_agent,
            "locale": self.locale,
            "country": self.country,
            "country_code": self.country_code,
            "timezone_offset": self.timezone_offset,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceFingerprint":
        return cls(
            settings=data["settings"],
            user_agent=data["user_agent"],
            locale=data["locale"],
            country=data["country"],
            country_code=int(data["country_code"]),
            timezone_offset=int(data["timezone_offset"]),
        )


def _build_user_agent(
    app_version: str,
    version_code: str,
    locale: str,
    dpi: str,
    resolution: str,
    manufacturer: str,
    model: str,
    codename: str,
    android_version: int,
    android_release: str,
    chipset: str,
) -> str:
    return (
        f"Instagram {app_version} Android "
        f"({android_version}/{android_release}; {dpi}; {resolution}; "
        f"{manufacturer}; {model}; {codename}; {chipset}; {locale}; {version_code})"
    )


def _new_uuids() -> dict[str, str]:
    return {
        "phone_id": str(uuid.uuid4()),
        "uuid": str(uuid.uuid4()),
        "client_session_id": str(uuid.uuid4()),
        "advertising_id": str(uuid.uuid4()),
        "device_id": f"android-{secrets.token_hex(8)}",
        "family_device_id": f"android-{secrets.token_hex(8)}",
        "pigeon_session_id": f"UFS-{uuid.uuid4()}-0",
    }


def generate_fingerprint(
    country: str = "US",
    rng: random.Random | None = None,
    *,
    timezone_id: str | None = None,
) -> DeviceFingerprint:
    """Generate a brand-new fingerprint suitable for ``client.set_settings``.

    When *timezone_id* is a valid IANA zone, ``timezone_offset`` is derived from
    it so the API client matches Playwright / account scheduling.
    """
    from app.geo.timezone_normalize import iana_utc_offset_seconds

    rng = rng or random.Random()
    country = country.upper()
    geo = _GEO_PROFILES.get(country, _GEO_PROFILES["US"])

    manufacturer, model, codename, android_version, android_release, dpi, resolution, chipset = rng.choice(_DEVICE_POOL)
    app_version, version_code = rng.choice(_APP_VERSIONS)
    locale: str = rng.choice(geo["locales"])
    if timezone_id:
        try:
            timezone_offset = iana_utc_offset_seconds(timezone_id)
        except Exception:
            timezone_offset = int(rng.choice(geo["timezone_offsets"]))
    else:
        timezone_offset = int(rng.choice(geo["timezone_offsets"]))

    device_settings = {
        "app_version": app_version,
        "android_version": android_version,
        "android_release": android_release,
        "dpi": dpi,
        "resolution": resolution,
        "manufacturer": manufacturer,
        "device": codename,
        "model": model,
        "cpu": chipset,
        "version_code": version_code,
    }

    user_agent = _build_user_agent(
        app_version=app_version,
        version_code=version_code,
        locale=locale,
        dpi=dpi,
        resolution=resolution,
        manufacturer=manufacturer,
        model=model,
        codename=codename,
        android_version=android_version,
        android_release=android_release,
        chipset=chipset,
    )

    full_settings = {
        "uuids": _new_uuids(),
        "mid": "",
        "ig_u_rur": "",
        "ig_www_claim": "",
        "authorization_data": {},
        "cookies": {},
        "last_login": 0,
        "device_settings": device_settings,
        "user_agent": user_agent,
        "country": country,
        "country_code": int(geo["country_code"]),
        "locale": locale,
        "timezone_offset": timezone_offset,
    }

    return DeviceFingerprint(
        settings=full_settings,
        user_agent=user_agent,
        locale=locale,
        country=country,
        country_code=int(geo["country_code"]),
        timezone_offset=timezone_offset,
    )


def device_path(username: str) -> Path:
    return settings.devices_dir / f"device_{username}.json"


def load_fingerprint(username: str) -> DeviceFingerprint | None:
    path = device_path(username)
    if not path.exists():
        return None
    try:
        return DeviceFingerprint.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("device.load_failed", username=username, error=str(exc))
        return None


def save_fingerprint(username: str, fp: DeviceFingerprint) -> Path:
    path = device_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fp.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def get_or_create_fingerprint(
    username: str,
    country: str = "US",
    *,
    timezone_id: str | None = None,
) -> DeviceFingerprint:
    existing = load_fingerprint(username)
    if existing:
        if timezone_id:
            align_fingerprint_timezone(existing, timezone_id)
            save_fingerprint(username, existing)
        return existing
    fp = generate_fingerprint(country=country, timezone_id=timezone_id)
    save_fingerprint(username, fp)
    logger.info("device.created", username=username, country=country, model=fp.settings["device_settings"]["model"])
    return fp


def align_fingerprint_timezone(fp: DeviceFingerprint, timezone_id: str) -> bool:
    """Update only ``timezone_offset`` to match *timezone_id*. Returns True if changed."""
    from app.geo.timezone_normalize import iana_utc_offset_seconds

    try:
        offset = iana_utc_offset_seconds(timezone_id)
    except Exception:
        return False
    if fp.timezone_offset == offset and fp.settings.get("timezone_offset") == offset:
        return False
    fp.timezone_offset = offset
    fp.settings["timezone_offset"] = offset
    return True


def rotate_session_uuids(fp: DeviceFingerprint) -> DeviceFingerprint:
    """Refresh ``client_session_id``, ``pigeon_session_id`` (and the WWW request id).

    These ids represent "this app launch" / "this UI session" — a real client
    rotates them periodically. Hardware ids (``device_id``, ``family_device_id``,
    ``phone_id``, ``advertising_id``, ``uuid``) are intentionally **not**
    touched: rotating them would look like the user reinstalled the app or
    changed device, which is a much rarer event than starting a fresh session.
    """
    uuids = fp.settings.setdefault("uuids", {})
    uuids["client_session_id"] = str(uuid.uuid4())
    uuids["pigeon_session_id"] = f"UFS-{uuid.uuid4()}-0"
    return fp
