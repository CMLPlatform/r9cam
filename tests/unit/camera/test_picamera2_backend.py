"""Tests for the Picamera2 backend implementation."""

import asyncio
import enum
import threading
import types
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from r9cam_models.camera import CameraMode
from r9cam_models.stream import StreamMode

from app.camera.exceptions import YoutubeConfigRequiredError
from app.camera.schemas import FocusControlRequest, FocusMode
from app.camera.services import picamera2_backend as backend_mod
from app.camera.services.picamera2_backend import Picamera2Backend

# ``libcamera`` is only installable on Raspberry Pi OS (ships via apt, not pip).
# Off-Pi a stub with the same enum values stands in; the real module is kept when present.
try:
    from libcamera import controls  # ty: ignore[unresolved-import]
except ImportError:

    class _AfModeEnum(enum.Enum):
        Manual = 0
        Auto = 1
        Continuous = 2

    class _AfStateEnum(enum.Enum):
        Idle = 0
        Scanning = 1
        Focused = 2
        Failed = 3

    controls = types.SimpleNamespace(AfModeEnum=_AfModeEnum, AfStateEnum=_AfStateEnum)


@pytest.fixture(autouse=True)
def _libcamera_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the backend at the (real or stub) libcamera controls, which it binds at import."""
    monkeypatch.setattr(backend_mod, "controls", controls)


class TestPicamera2Backend:
    """Tests for the concrete Picamera2 backend."""

    _NAMESPACE = "picamera2"
    _AF_MODE_AUTO = "Auto"
    _AF_STATE_FOCUSED = "Focused"

    async def test_open_is_idempotent_once_started(self) -> None:
        """Opening again after the pipeline is running should not reconfigure."""
        backend = Picamera2Backend()
        camera = MagicMock()
        cast("Any", backend)._camera = camera
        backend.current_mode = CameraMode.PHOTO

        await backend.open(CameraMode.VIDEO)

        camera.configure.assert_not_called()
        camera.start.assert_not_called()
        assert backend.current_mode == CameraMode.VIDEO

    async def test_open_enables_continuous_autofocus_when_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Opening should default to continuous autofocus when AfMode is available."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_controls = {"AfMode": (0, 2, 1)}
        camera.create_video_configuration.return_value = {"config": "video"}
        monkeypatch.setattr("app.camera.services.picamera2_backend.Picamera2", MagicMock(return_value=camera))

        await backend.open(CameraMode.VIDEO)

        camera.set_controls.assert_called_once_with({"AfMode": controls.AfModeEnum.Continuous})

    async def test_open_skips_autofocus_when_not_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Opening should not touch focus controls when AfMode is absent."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_controls = {"ExposureTime": (1, 1000, 100)}
        camera.create_video_configuration.return_value = {"config": "video"}
        monkeypatch.setattr("app.camera.services.picamera2_backend.Picamera2", MagicMock(return_value=camera))

        await backend.open(CameraMode.VIDEO)

        camera.set_controls.assert_not_called()

    async def test_capture_image_reads_main_stream(self) -> None:
        """capture_image must pull from the persistent main stream by name."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_properties = {"Model": "mock"}
        camera.capture_metadata.return_value = {"FrameDuration": 33_333}
        camera.capture_image.return_value = MagicMock()
        cast("Any", backend)._camera = camera
        backend.current_mode = CameraMode.PHOTO

        await backend.capture_image()

        camera.capture_image.assert_called_once_with("main")

    async def test_start_stream_requires_config(self) -> None:
        """YouTube streaming should require YouTube config."""
        backend = Picamera2Backend()

        with pytest.raises(YoutubeConfigRequiredError):
            await backend.start_stream(StreamMode.YOUTUBE, youtube_config=None)

    async def test_stop_stream_keeps_camera_running(self) -> None:
        """stop_stream must only detach the encoder — the camera pipeline stays up for stills."""
        backend = Picamera2Backend()
        camera = MagicMock()
        encoder = MagicMock()
        mediamtx = cast("Any", backend._mediamtx)
        mediamtx.clear_egress = AsyncMock()
        cast("Any", backend)._camera = camera
        cast("Any", backend)._main_encoder = encoder

        await backend.stop_stream()

        camera.stop_encoder.assert_called_once_with(encoder)
        assert backend._main_encoder is None
        camera.stop.assert_not_called()
        camera.start.assert_not_called()

    async def test_get_controls_returns_camera_controls_and_metadata(self) -> None:
        """get_controls should expose Picamera2 camera_controls and latest metadata."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_controls = {
            "AfMode": (controls.AfModeEnum.Manual, controls.AfModeEnum.Continuous, controls.AfModeEnum.Auto),
            "ExposureTime": (1, 1_000_000, 10_000),
        }
        camera.capture_metadata.return_value = {"AfState": controls.AfStateEnum.Focused, "ExposureTime": 10_000}
        cast("Any", backend)._camera = camera
        backend.current_mode = CameraMode.VIDEO

        view = await backend.get_controls()

        assert view.supported is True
        assert view.controls["AfMode"].namespace == self._NAMESPACE
        assert view.controls["AfMode"].options == ["manual", "auto", "continuous"]
        assert view.controls["AfMode"].default == self._AF_MODE_AUTO
        assert view.values["AfState"] == self._AF_STATE_FOCUSED
        assert view.values["ExposureTime"] == 10_000

    async def test_set_controls_maps_afmode_string(self) -> None:
        """set_controls should accept friendly AfMode strings for the generic endpoint."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_controls = {"AfMode": (0, 2, 1)}
        camera.capture_metadata.return_value = {"AfState": controls.AfStateEnum.Focused}
        cast("Any", backend)._camera = camera
        backend.current_mode = CameraMode.VIDEO

        await backend.set_controls({"AfMode": "continuous"})

        camera.set_controls.assert_called_once_with({"AfMode": controls.AfModeEnum.Continuous})

    async def test_set_focus_continuous_maps_to_afmode(self) -> None:
        """set_focus should map continuous mode to the libcamera enum."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_controls = {"AfMode": (0, 2, 1)}
        camera.capture_metadata.return_value = {}
        cast("Any", backend)._camera = camera
        backend.current_mode = CameraMode.VIDEO

        await backend.set_focus(FocusControlRequest(mode=FocusMode.CONTINUOUS))

        camera.set_controls.assert_called_once_with({"AfMode": controls.AfModeEnum.Continuous})

    async def test_set_focus_auto_cycle_uses_autofocus_cycle(self) -> None:
        """set_focus should run the Picamera2 autofocus cycle for one-shot autofocus."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_controls = {"AfMode": (0, 2, 1)}
        camera.capture_metadata.return_value = {}
        cast("Any", backend)._camera = camera
        backend.current_mode = CameraMode.VIDEO

        await backend.set_focus(FocusControlRequest(mode=FocusMode.AUTO, trigger_cycle=True))

        camera.autofocus_cycle.assert_called_once_with(wait=True)
        camera.set_controls.assert_not_called()

    async def test_set_focus_manual_sets_lens_position(self) -> None:
        """set_focus should pass manual lens position through to Picamera2."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.camera_controls = {"AfMode": (0, 2, 1), "LensPosition": (0.0, 10.0, 1.0)}
        camera.capture_metadata.return_value = {}
        backend._camera = camera
        backend.current_mode = CameraMode.VIDEO

        await backend.set_focus(FocusControlRequest(mode=FocusMode.MANUAL, lens_position=2.5))

        camera.set_controls.assert_called_once_with({"AfMode": controls.AfModeEnum.Manual, "LensPosition": 2.5})

    async def test_capture_preview_frame_reads_main_stream(self) -> None:
        """Preview frames come from the main stream, opening VIDEO mode first."""
        backend = Picamera2Backend()
        camera = MagicMock()
        cast("Any", backend)._camera = camera

        await backend.capture_preview_frame()

        camera.capture_image.assert_called_once_with("main")
        assert backend.current_mode == CameraMode.VIDEO

    async def test_start_lores_encoder_passes_name(self) -> None:
        """The lores encoder is attached by stream name."""
        backend = Picamera2Backend()
        camera = MagicMock()
        cast("Any", backend)._camera = camera

        await backend.start_lores_encoder("enc", "out")

        camera.start_encoder.assert_called_once_with("enc", "out", name="lores")

    async def test_start_lores_encoder_failure_maps_to_runtime_error(self) -> None:
        """An encoder start error surfaces as RuntimeError."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.start_encoder.side_effect = OSError("boom")
        cast("Any", backend)._camera = camera

        with pytest.raises(RuntimeError, match="failed to start"):
            await backend.start_lores_encoder("enc", "out")

    async def test_late_lores_start_is_stopped_after_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A start that finishes after the deadline is stopped, not left untracked."""
        monkeypatch.setattr(backend_mod, "_ENCODER_START_TIMEOUT_S", 0.05)
        release = threading.Event()
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.start_encoder.side_effect = lambda *_a, **_k: release.wait(5)
        cast("Any", backend)._camera = camera

        with pytest.raises(RuntimeError, match="startup timeout"):
            await backend.start_lores_encoder("enc", "out")
        camera.stop_encoder.assert_not_called()

        release.set()
        for _ in range(100):
            if camera.stop_encoder.called:
                break
            await asyncio.sleep(0.02)
        camera.stop_encoder.assert_called_once_with("enc")

    async def test_stop_stream_clears_encoder_when_stop_raises(self) -> None:
        """A failing stop_encoder must not leave the main encoder tracked."""
        backend = Picamera2Backend()
        camera = MagicMock()
        camera.stop_encoder.side_effect = RuntimeError("boom")
        cast("Any", backend._mediamtx).clear_egress = AsyncMock()
        cast("Any", backend)._camera = camera
        cast("Any", backend)._main_encoder = MagicMock()

        with pytest.raises(RuntimeError, match="boom"):
            await backend.stop_stream()

        assert backend._main_encoder is None
