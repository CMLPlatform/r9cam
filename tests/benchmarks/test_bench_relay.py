"""Benchmarks for the backend<->Pi relay seam: command parsing, allowlisting and responses."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from r9cam_models.device_seam import (
    RelayCommandEnvelope,
    RelayResponseEnvelope,
    build_relay_command,
    relay_command_is_allowed,
    relay_content_type_is_binary,
)

if TYPE_CHECKING:
    from pytest_codspeed import BenchmarkFixture

_RELAY_PATHS: tuple[tuple[str, str], ...] = (
    ("GET", "/camera"),
    ("POST", "/captures"),
    ("GET", "/preview/hls/cam/index.m3u8"),
    ("GET", "/preview/hls/cam/segment%2F..%2F..%2Fetc%2Fpasswd"),
    ("GET", "/%252e%252e/secret"),
    ("DELETE", "/camera/"),
    ("PATCH", "/camera/controls"),
    ("GET", "relative/path"),
)

_COMMAND_JSON = json.dumps(
    {
        "id": "msg-0123456789abcdef",
        "type": "request",
        "method": "POST",
        "path": "/captures",
        "params": {"upload": True, "quality": 90, "ratio": 1.5, "label": "bench"},
        "body": {"upload_metadata": {"product_id": 42, "tags": ["a", "b", "c"], "note": "benchmark"}},
        "headers": {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"},
    }
)

_RESPONSE_DATA = {
    "image_id": "0123456789abcdef0123456789abcdef",
    "status": "uploaded",
    "metadata": {"camera_properties": {"camera_model": "imx708"}, "capture_metadata": {"lux": 120.5}},
}


def test_relay_command_allowlist(benchmark: BenchmarkFixture) -> None:
    """Check a mix of allowed, denied, and traversal-encoded relay paths."""

    def check_all() -> list[bool]:
        return [relay_command_is_allowed(method, path) for method, path in _RELAY_PATHS]

    result = benchmark(check_all)

    assert any(result)
    assert not all(result)


def test_parse_relay_command(benchmark: BenchmarkFixture) -> None:
    """Validate an incoming relay command frame from raw JSON."""
    result = benchmark(RelayCommandEnvelope.model_validate_json, _COMMAND_JSON)

    assert result.method == "POST"


def test_build_relay_command(benchmark: BenchmarkFixture) -> None:
    """Build a relay command envelope, filtering untrusted headers."""
    headers = {
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        "tracestate": "vendor=value",
        "Authorization": "Bearer should-be-dropped",
        "Cookie": "session=dropped",
    }

    result = benchmark(
        build_relay_command,
        "msg-1",
        "get",
        "/preview/hls/cam/index.m3u8",
        {"_HLS_msn": 12, "_HLS_part": 3},
        None,
        headers,
    )

    assert "authorization" not in result.headers


def test_serialize_relay_response(benchmark: BenchmarkFixture) -> None:
    """Build and serialize a relay response header frame."""

    def build_and_dump() -> str:
        content_type = "application/json; charset=utf-8"
        envelope = RelayResponseEnvelope(
            id="msg-0123456789abcdef",
            status=200,
            content_type=content_type,
            has_binary=relay_content_type_is_binary(content_type),
            data=_RESPONSE_DATA,
        )
        return envelope.model_dump_json(exclude_none=True)

    result = benchmark(build_and_dump)

    assert '"status":200' in result
