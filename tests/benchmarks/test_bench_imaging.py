"""Benchmarks for in-memory JPEG encoding on the capture and preview paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from app.camera.services.manager import encode_preview_jpeg

if TYPE_CHECKING:
    from pytest_codspeed import BenchmarkFixture


def _gradient_image(width: int, height: int) -> Image.Image:
    """Build a deterministic RGB frame with enough detail to exercise the encoder."""
    red = Image.linear_gradient("L").resize((width, height))
    green = red.rotate(90).resize((width, height))
    blue = Image.effect_noise((width, height), 64)
    return Image.merge("RGB", (red, green, blue))


@pytest.fixture(scope="module")
def capture_frame() -> Image.Image:
    """Return a 1280x720 frame, the default still-capture size used in tests."""
    return _gradient_image(1280, 720)


def test_encode_preview_thumbnail(benchmark: BenchmarkFixture, capture_frame: Image.Image) -> None:
    """Downscale and optimize a frame into the cached preview thumbnail."""
    result = benchmark(encode_preview_jpeg, capture_frame)

    assert result[:2] == b"\xff\xd8"
