"""Type-only protocols for optional hardware-backed dependencies."""

from typing import Any, Protocol

from PIL.Image import Image as PilImage


class Picamera2Like(Protocol):
    """Behavior required from a Picamera2-compatible camera object."""

    camera_properties: dict[str, Any]
    camera_controls: dict[str, tuple[Any, Any, Any]]

    def configure(self, config: object) -> None:
        """Configure the camera for the next capture or recording."""

    def start(self) -> None:
        """Start the camera."""

    def stop(self) -> None:
        """Stop the camera."""

    def close(self) -> None:
        """Release the camera."""

    def capture_image(self, name: str = "main") -> PilImage:
        """Capture a still image from the named stream (PIL Image at runtime)."""

    def capture_metadata(self) -> dict | None:
        """Capture metadata for the last image or frame."""

    def start_encoder(self, encoder: object, output: object, *, name: str = "main") -> None:
        """Attach an encoder to a named stream without restarting the camera."""

    def stop_encoder(self, encoders: object | None = None) -> None:
        """Detach one, many, or all encoders."""

    def set_controls(self, controls: dict[str, object]) -> None:
        """Set runtime camera controls."""

    def autofocus_cycle(self, *, wait: bool | None = None, signal_function: object | None = None) -> object:
        """Run a Picamera2 autofocus cycle."""

    def create_video_configuration(self, **kwargs: object) -> dict:
        """Create a video capture configuration."""
