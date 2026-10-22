"""Benchmarks for request/response schema validation and serialization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from r9cam_models.images import ImageCaptureResponse

from app.camera.schemas import CaptureUploadMetadata

if TYPE_CHECKING:
    from pytest_codspeed import BenchmarkFixture

_UPLOAD_METADATA = {
    "product_id": 1234,
    "session": "bench-session-0001",
    "tags": ["front", "left", "macro", "daylight"],
    "position": {"x": 1.25, "y": -3.5, "z": 0.0, "rotation": {"pitch": 10, "yaw": 45, "roll": 0}},
    "operator": {"name": "Bench Operator", "station": 7, "verified": True},
    "notes": None,
    "samples": [{"id": i, "weight": i * 0.5, "label": f"sample-{i}"} for i in range(8)],
}


_LIBCAMERA_CAPTURE = {
    "image_id": "0123456789abcdef0123456789abcdef",
    "status": "uploaded",
    "image_url": "https://backend.example/images/0123456789abcdef0123456789abcdef.jpg",
    "metadata": {
        "camera_properties": {
            "Model": "imx708",
            "UnitCellSize": [1400, 1400],
            "PixelArraySize": [4608, 2592],
            "SensorSensitivity": 1.0,
        },
        "capture_metadata": {
            "ExposureTime": 20000,
            "FrameDuration": 33333,
            "ColourTemperature": 5200,
            "AnalogueGain": 2.0,
            "DigitalGain": 1.0,
            "Lux": 320.5,
            "SensorTemperature": 41.0,
        },
        "image_properties": {
            "width": 4608,
            "height": 2592,
            "capture_time": datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        },
    },
}


def test_validate_upload_metadata(benchmark: BenchmarkFixture) -> None:
    """Validate bounded opaque upload metadata forwarded to the image sink."""
    result = benchmark(CaptureUploadMetadata.model_validate, _UPLOAD_METADATA)

    assert result.root["product_id"] == 1234


def test_capture_response_roundtrip(benchmark: BenchmarkFixture) -> None:
    """Parse libcamera-shaped capture metadata and serialize the API response."""

    def roundtrip() -> str:
        return ImageCaptureResponse.model_validate(_LIBCAMERA_CAPTURE).model_dump_json(by_alias=True)

    result = benchmark(roundtrip)

    assert '"capture_time":"2025-01-01T12:00:00Z"' in result
