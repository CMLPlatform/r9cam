"""Property tests for the EXIF block written into captured JPEGs."""

from datetime import UTC
from io import BytesIO

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image
from PIL.ExifTags import IFD, Base
from r9cam_models.images import CameraProperties, CaptureMetadata, ImageMetadata, ImageProperties

from app.backend.contract_adapters import image_metadata_to_exif
from app.camera.services.manager import _encode_jpeg

# EXIF stores these as 32-bit rationals, so a float read back is only as exact as its fraction.
_RATIONAL_REL_TOLERANCE = 1e-6
_RATIONAL_ABS_TOLERANCE = 1e-6

# The text strategy covers non-ASCII camera models on purpose: EXIF Model is an ASCII tag.
_camera_properties = st.builds(CameraProperties, camera_model=st.none() | st.text(max_size=40))
# Exposure times up to about 30 minutes and sensor readings from a freezer to an overheating board.
_capture_metadata = st.builds(
    CaptureMetadata,
    exposure_time=st.none() | st.integers(min_value=1, max_value=2_000_000_000),
    sensor_temperature=st.none() | st.floats(min_value=-273.15, max_value=200.0, allow_nan=False, allow_infinity=False),
)
_image_properties = st.builds(
    ImageProperties,
    width=st.integers(min_value=1, max_value=8),
    height=st.integers(min_value=1, max_value=8),
    capture_time=st.datetimes(timezones=st.just(UTC)),
)
_image_metadata = st.builds(
    ImageMetadata,
    camera_properties=_camera_properties,
    capture_metadata=_capture_metadata,
    image_properties=_image_properties,
)


@settings(max_examples=25, deadline=None)
@given(metadata=_image_metadata)
def test_property_exif_round_trip_keeps_exposure_and_temperature(metadata: ImageMetadata) -> None:
    """Exposure time and sensor temperature survive encoding and reading back with Pillow."""
    width, height = metadata.image_properties.width, metadata.image_properties.height
    jpeg = _encode_jpeg(Image.new("RGB", (width, height)), image_metadata_to_exif(metadata))

    with Image.open(BytesIO(jpeg)) as decoded:
        exif_ifd = decoded.getexif().get_ifd(IFD.Exif)

    exposure_us = metadata.capture_metadata.exposure_time
    if exposure_us is None:
        assert Base.ExposureTime.value not in exif_ifd
    else:
        assert float(exif_ifd[Base.ExposureTime.value]) == pytest.approx(
            exposure_us / 1_000_000, rel=_RATIONAL_REL_TOLERANCE, abs=_RATIONAL_ABS_TOLERANCE
        )

    temperature = metadata.capture_metadata.sensor_temperature
    if temperature is None:
        assert Base.AmbientTemperature.value not in exif_ifd
    else:
        assert float(exif_ifd[Base.AmbientTemperature.value]) == pytest.approx(
            temperature, rel=_RATIONAL_REL_TOLERANCE, abs=_RATIONAL_ABS_TOLERANCE
        )
