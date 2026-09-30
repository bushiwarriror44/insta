"""Media path helpers."""
from datetime import datetime, timezone

import pytest

from app.db.models import MediaAsset
from app.services.media import MediaError, asset_media_path, resolve


def test_resolve_rejects_path_traversal(app_env):
    with pytest.raises(MediaError, match="escapes"):
        resolve(app_env.tmp_path / "media", "../outside.mp4")


def test_asset_media_path_removed_asset(app_env):
    asset = MediaAsset(
        filename="gone.mp4",
        file_removed_at=datetime.now(timezone.utc),
    )
    with pytest.raises(MediaError, match="удалён"):
        asset_media_path(app_env.tmp_path, asset)


def test_asset_media_path_missing_file(app_env):
    asset = MediaAsset(filename="missing.mp4")
    with pytest.raises(MediaError, match="отсутствует"):
        asset_media_path(app_env.tmp_path, asset)


def test_asset_media_path_ok(app_env):
    media = app_env.tmp_path
    (media / "clip.mp4").write_bytes(b"x")
    asset = MediaAsset(filename="clip.mp4")
    path = asset_media_path(media, asset)
    assert path.name == "clip.mp4"
    assert path.is_file()
