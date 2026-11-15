"""The relay_max_* settings must bound the receive loop's real behaviour."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import ValidationError

from app.core.runtime_state import RuntimeState
from app.core.settings import Settings, settings
from app.relay.service import _receive_loop
from app.relay.state import RelayRuntimeState

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

_SETTLE_TICKS = 50


class _Harness:
    """A fake backend socket plus a local app that blocks every request until released."""

    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.release = asyncio.Event()
        self.in_flight = 0
        self.max_in_flight = 0
        self.sent: list[dict[str, Any]] = []

    async def app(self, _scope: Any, _receive: Any, send: Any) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await self.release.wait()
        self.in_flight -= 1
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"{}"})

    async def send(self, frame: str | bytes) -> None:
        self.sent.append(json.loads(frame))

    async def __aiter__(self) -> AsyncIterator[str]:
        for msg_id in self.ids:
            yield json.dumps({"type": "request", "id": msg_id, "method": "GET", "path": "/camera"})
        for _ in range(_SETTLE_TICKS):
            await asyncio.sleep(0)
        self.release.set()

    async def run(self, **caps: int) -> dict[str, int]:
        await _receive_loop(
            cast("ClientConnection", self),
            asgi_app=self.app,
            relay_state=RelayRuntimeState(),
            runtime_state=RuntimeState(),
            app_settings=settings.model_copy(update=caps),
        )
        return {m["id"]: m["status"] for m in self.sent}


async def test_pending_cap_rejects_the_excess_with_429() -> None:
    """Commands past relay_max_pending_commands get a 429 reply."""
    statuses = await _Harness(["a", "b", "c"]).run(relay_max_pending_commands=2, relay_max_concurrent_commands=1)

    assert statuses == {"a": 200, "b": 200, "c": 429}


async def test_concurrency_cap_limits_commands_in_flight() -> None:
    """No more than relay_max_concurrent_commands run at once, and all finish."""
    harness = _Harness(["a", "b", "c", "d", "e"])

    statuses = await harness.run(relay_max_pending_commands=10, relay_max_concurrent_commands=2)

    assert harness.max_in_flight == 2
    assert set(statuses.values()) == {200}
    assert len(statuses) == 5


@pytest.mark.parametrize("field", ["relay_max_pending_commands", "relay_max_concurrent_commands"])
def test_caps_reject_zero(field: str) -> None:
    """A zero cap would deadlock or reject everything, so settings refuse it."""
    with pytest.raises(ValidationError):
        Settings.model_validate({field: 0})
