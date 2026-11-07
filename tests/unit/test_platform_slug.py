from __future__ import annotations

from types import SimpleNamespace

from app.accounts.platform_slug import normalize_platform_slug
from app.db.models import Platform


def test_normalize_platform_enum_value():
    assert normalize_platform_slug(Platform.youtube) == "youtube"


def test_normalize_platform_string_label():
    assert normalize_platform_slug("Platform.youtube") == "youtube"


def test_normalize_account_platform():
    account = SimpleNamespace(platform=Platform.tiktok)
    from app.accounts.platform_slug import normalize_platform_slug

    assert normalize_platform_slug(account.platform) == "tiktok"
