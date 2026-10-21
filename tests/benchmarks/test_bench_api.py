"""Benchmarks for full request handling through the ASGI app and middleware stack."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import verify_request
from tests.conftest import TEST_API_KEY

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from pytest_codspeed import BenchmarkFixture


@pytest.fixture
def api(test_app: FastAPI) -> Iterator[tuple[asyncio.AbstractEventLoop, AsyncClient]]:
    """Return a private event loop and an authenticated ASGI client bound to it."""

    async def _override_auth() -> str:
        return TEST_API_KEY

    test_app.dependency_overrides[verify_request] = _override_auth
    loop = asyncio.new_event_loop()
    client = AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test")
    try:
        yield loop, client
    finally:
        loop.run_until_complete(client.aclose())
        loop.close()


def test_get_healthz(benchmark: BenchmarkFixture, api: tuple[asyncio.AbstractEventLoop, AsyncClient]) -> None:
    """Serve the unauthenticated LAN liveness probe through all middleware."""
    loop, client = api

    response = benchmark(lambda: loop.run_until_complete(client.get("/healthz")))

    assert response.status_code == 200


def test_get_camera_status(benchmark: BenchmarkFixture, api: tuple[asyncio.AbstractEventLoop, AsyncClient]) -> None:
    """Serve the authenticated camera status endpoint."""
    loop, client = api

    response = benchmark(lambda: loop.run_until_complete(client.get("/camera")))

    assert response.status_code == 200


def test_patch_camera_controls(benchmark: BenchmarkFixture, api: tuple[asyncio.AbstractEventLoop, AsyncClient]) -> None:
    """Validate and apply a camera-controls patch end to end."""
    loop, client = api
    payload = {"controls": {"ExposureTime": 10000, "AnalogueGain": 1.5, "AfMode": "auto"}}

    response = benchmark(lambda: loop.run_until_complete(client.patch("/camera/controls", json=payload)))

    assert response.status_code == 200
