"""Benchmarks for the backend<->Pi relay seam: command parsing, allowlisting and responses."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from r9cam_models.device_seam import (
    RelayCommandEnvelope,
    RelayResponseEnvelope,
    relay_command_is_allowed,
    relay_content_type_is_binary,
)

from app.auth.dependencies import verify_request
from app.relay.service import _handle_command
from tests.conftest import TEST_API_KEY

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_codspeed import BenchmarkFixture
    from websockets.asyncio.client import ClientConnection

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
    """Decode and validate an incoming relay command frame the way the relay service does."""
    result = benchmark(lambda: RelayCommandEnvelope.model_validate(json.loads(_COMMAND_JSON)))

    assert result.method == "POST"


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
        return envelope.model_dump_json()

    result = benchmark(build_and_dump)

    assert '"status":200' in result


_SEGMENT = b"\x47" * 100_000


@pytest.fixture
def relay(test_app: FastAPI) -> Iterator[tuple[asyncio.AbstractEventLoop, AsyncClient]]:
    """Return a private event loop and a client into the app, plus a stub binary route."""

    async def _override_auth() -> str:
        return TEST_API_KEY

    test_app.dependency_overrides[verify_request] = _override_auth
    # Stub route, put first so it wins: the real segment route needs a running HLS preview.
    test_app.add_api_route(
        "/preview/hls/{camera}/{segment}",
        lambda: Response(_SEGMENT, media_type="video/mp2t"),
        methods=["GET"],
    )
    stub = test_app.router.routes.pop()
    test_app.router.routes.insert(0, stub)
    loop = asyncio.new_event_loop()
    client = AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test")
    try:
        yield loop, client
    finally:
        # test_app is the global app: drop the stub so it does not leak into other tests.
        test_app.router.routes.remove(stub)
        loop.run_until_complete(client.aclose())
        loop.close()


def _handle(relay: tuple[asyncio.AbstractEventLoop, AsyncClient], path: str) -> AsyncMock:
    loop, client = relay
    ws = AsyncMock()
    msg = {"id": "msg-0123456789abcdef", "type": "request", "method": "GET", "path": path}
    loop.run_until_complete(_handle_command(cast("ClientConnection", ws), client, msg))
    return ws


def test_handle_command_json(benchmark: BenchmarkFixture, relay: tuple[asyncio.AbstractEventLoop, AsyncClient]) -> None:
    """Relay an allowlisted GET with a JSON body: route, envelope and one send."""
    ws = benchmark(lambda: _handle(relay, "/camera"))

    assert '"status":200' in ws.send.await_args.args[0]


def test_handle_command_binary(
    benchmark: BenchmarkFixture, relay: tuple[asyncio.AbstractEventLoop, AsyncClient]
) -> None:
    """Relay an allowlisted GET with a 100 KB binary body: header frame plus body frame."""
    ws = benchmark(lambda: _handle(relay, "/preview/hls/cam/seg0.ts"))

    assert ws.send.await_args.args[0] == _SEGMENT
