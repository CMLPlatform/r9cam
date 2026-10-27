"""Runtime fallbacks for picamera2 when running on non-Raspberry Pi hosts."""

from typing import Any, ClassVar

_ERR = "picamera2 is not available; camera operations require a Raspberry Pi."


class Picamera2Stub:
    """Stub used on non-Raspberry Pi hosts so the app can start."""

    camera_properties: ClassVar[dict[str, Any]] = {}
    camera_controls: ClassVar[dict[str, tuple[Any, Any, Any]]] = {}

    def __init__(self, _camera_num: int = 0) -> None:
        raise RuntimeError(_ERR)


class H264EncoderStub:
    """Stub used on non-Raspberry Pi hosts so the app can start."""

    # Present on the runtime encoder; declare for static checkers/tests.
    bitrate: ClassVar[int | None] = None

    def __init__(self) -> None:
        raise RuntimeError(_ERR)


class FfmpegOutputStub:
    """Stub for non-Raspberry Pi environments."""

    def __init__(self, _output_str: str, /, **_kwargs: object) -> None:
        raise RuntimeError(_ERR)
