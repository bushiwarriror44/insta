"""Docs stay aligned with generation, handbook, and fal pricing."""
from __future__ import annotations

from pathlib import Path

from app.generation.fal import RATE_USD_PER_SECOND

ROOT = Path(__file__).resolve().parents[2]


def test_generation_md_describes_preview_and_slideshow():
    text = (ROOT / "docs" / "generation.md").read_text(encoding="utf-8")
    assert "Превью" in text
    assert "PlanJob" in text
    assert "auto_schedule=false" in text
    assert "image_slideshow" in text
    assert "backend принудительно `slideshow`" in text
    assert "video_source_dir" in text or "data/videos/source" in text


def test_handbook_preview_plan_matches_generation_semantics():
    text = (ROOT / "docs" / "assistant-handbook.md").read_text(encoding="utf-8")
    assert "preview_plan" in text
    assert "GenerationJob" in text
    assert "auto_schedule=false" in text


def test_costs_md_matches_fal_wan_rates():
    text = (ROOT / "docs" / "costs.md").read_text(encoding="utf-8")
    wan_rate = RATE_USD_PER_SECOND["fal-ai/wan-25-preview/text-to-video"]
    assert wan_rate == 0.05
    assert "0.05" in text
    assert "fal.py" in text or "fal" in text.lower()
