import pytest

from app.config import Settings
from app.generation.base import GenerationError, GenerationRequest
from app.generation.fal import FalVideoBackend, aspect_ratio


def settings(**over) -> Settings:
    return Settings(
        fal_api_key=over.pop("fal_api_key", "key-123"),
        generation_poll_seconds=0,
        generation_timeout_seconds=over.pop("generation_timeout_seconds", 30),
        **over,
    )


@pytest.fixture
def backend():
    return FalVideoBackend(settings())


@pytest.mark.parametrize(
    ("size", "expected"),
    [((720, 1280), "9:16"), ((1920, 1080), "16:9"), ((1024, 1024), "1:1")],
)
def test_frame_maps_to_the_nearest_ratio_fal_accepts(size, expected):
    assert aspect_ratio(*size) == expected


def test_zero_height_is_refused():
    with pytest.raises(GenerationError):
        aspect_ratio(720, 0)


def test_payload_snaps_duration_and_resolution_to_allowed_values(backend):
    payload = backend._payload(
        GenerationRequest(prompt="a ridge at dawn", duration_s=7, width=720, height=1280),
        duration=7,
    )
    assert payload["resolution"] == "720p"
    assert payload["aspect_ratio"] == "9:16"


def test_payload_trims_overlong_prompts(backend):
    payload = backend._payload(
        GenerationRequest(prompt="x" * 4000, negative_prompt="y" * 900), duration=5
    )
    assert len(payload["prompt"]) == 1500
    assert len(payload["negative_prompt"]) == 500
