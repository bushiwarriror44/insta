"""Unit tests for server-side image compression."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.video.image_compress import compress_image_file


def _save_png(path: Path, size: tuple[int, int] = (3200, 1800), mode: str = "RGB") -> Path:
    img = Image.new(mode, size, color=(40, 120, 200) if mode == "RGB" else (40, 120, 200, 128))
    img.save(path, format="PNG")
    return path


def test_compress_image_resizes_and_writes_jpeg(tmp_path: Path):
    src = _save_png(tmp_path / "wide.png", (3200, 1800))
    out = compress_image_file(src, max_edge=1920, quality=85)
    assert out.suffix.lower() == ".jpg"
    assert out.exists()
    assert not src.exists()
    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert max(img.size) == 1920
        assert img.mode == "RGB"


def test_compress_image_keeps_jpg_name(tmp_path: Path):
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (100, 80), color=(1, 2, 3)).save(src, format="JPEG", quality=95)
    out = compress_image_file(src, max_edge=1920, quality=70)
    assert out == src
    assert out.exists()


def test_compress_rgba_flattens_to_rgb(tmp_path: Path):
    src = _save_png(tmp_path / "alpha.png", (64, 64), mode="RGBA")
    out = compress_image_file(src, max_edge=1920, quality=85)
    with Image.open(out) as img:
        assert img.mode == "RGB"


def test_compress_rejects_bad_params(tmp_path: Path):
    src = _save_png(tmp_path / "ok.png", (32, 32))
    with pytest.raises(ValueError):
        compress_image_file(src, max_edge=0, quality=85)
    with pytest.raises(ValueError):
        compress_image_file(src, max_edge=100, quality=0)
