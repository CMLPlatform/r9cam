#!/usr/bin/env python3
"""Fuzz the relay trust boundary with raw backend frames.

Each input becomes one WebSocket text (or binary) frame and goes through
``_handle_relay_message`` exactly as the receive loop hands it over, with a real
httpx ``ASGITransport`` client behind it. The harness fails when:

- anything other than a ``ValidationError`` escapes the envelope, the allowlist or
  the header filter;
- a command task dies with an exception;
- a command reaches local dispatch without passing ``relay_command_is_allowed``;
- an allowlisted command routes in the local FastAPI app to a route outside the
  allowlist;
- the header filter lets through a header that is not a trace header.

Run it with ``uv run --group fuzz python fuzz/relay_frames.py -runs=20000 -seed=1``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

import atheris

# The app import pulls in the seam modules, so it sits inside the block. Only
# first-party code gets coverage instrumentation, which keeps startup short.
with atheris.instrument_imports(include=["app", "r9cam_models"]):
    import httpx
    from fastapi.routing import APIRoute
    from pydantic import ValidationError

    from app.main import app
    from app.relay.service import _handle_relay_message
    from app.relay.state import RelayRuntimeState
    from r9cam_models import (
        RELAY_ALLOWED_EXACT_COMMANDS,
        RELAY_ALLOWED_PREFIX_COMMANDS,
        RelayCommandEnvelope,
        extract_safe_relay_headers,
        relay_command_is_allowed,
    )

if TYPE_CHECKING:
    from starlette.types import Receive, Scope, Send

_TRACE_HEADERS = frozenset({"traceparent", "tracestate", "baggage"})
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "get", "pOsT", "")
_TYPES = ("request", "ping", "pong", "response", "REQUEST", "")
_PATH_STEMS = (
    *sorted({path for _, path in RELAY_ALLOWED_EXACT_COMMANDS}),
    *sorted({prefix for _, prefix in RELAY_ALLOWED_PREFIX_COMMANDS}),
    "/",
    "/auth/login",
    "/static/",
    "/local-key",
    "/system/",
    "%2F",
    "/..",
    "/%2e%2e/",
)
_HEADER_NAMES = (*sorted(_TRACE_HEADERS), "TraceParent", "authorization", "x-api-key", "cookie", "host")
_MAX_KEY_COUNT = 5
_MAX_TEXT = 64
_HTTP_SCOPE = "http"


class _FakeWebSocket:
    """Stand-in for the backend connection that only collects outbound frames."""

    def __init__(self) -> None:
        self.sent: list[str | bytes] = []

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)


class _RouteProbe:
    """ASGI app that lets the real router pick the route, then answers itself.

    ``APIRoute.handle`` is swapped for one that records the matched route and
    sends an empty 200, so no endpoint, dependency or middleware runs. A request
    no route takes is a 404, and one whose route lacks the method is a 405: both
    record nothing, since neither reaches an endpoint.
    """

    def __init__(self) -> None:
        self.requests = 0
        self.dispatched: list[tuple[str, str, APIRoute]] = []
        probe = self

        async def record(route: APIRoute, scope: Scope, _receive: Receive, send: Send) -> None:
            if scope["method"] in (route.methods or ()):
                probe.dispatched.append((scope["method"], scope["raw_path"].decode("latin-1"), route))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        APIRoute.handle = record  # ty: ignore[invalid-assignment]
        self._check_router()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != _HTTP_SCOPE:
            return
        self.requests += 1
        await app.router({**scope, "app": app}, receive, send)

    def _check_router(self) -> None:
        """Fail at startup if routing no longer reaches the routes, which would make every check pass."""

        async def resolve(method: str, path: str) -> str | None:
            self.dispatched.clear()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self), base_url="http://probe") as client:
                await client.request(method, path)
            return self.dispatched[0][2].path if self.dispatched else None

        for method, path in (("GET", "/camera"), ("POST", "/auth/login")):
            resolved = asyncio.run(resolve(method, path))
            if resolved != path:
                msg = f"route probe resolved {method} {path} to {resolved!r}; the router changed"
                raise RuntimeError(msg)


def _route_is_allowlisted(method: str, route: APIRoute) -> bool:
    """Return whether the route the router matched is one the allowlist names."""
    if (method, route.path) in RELAY_ALLOWED_EXACT_COMMANDS:
        return True
    return any(method == allowed and route.path.startswith(prefix) for allowed, prefix in RELAY_ALLOWED_PREFIX_COMMANDS)


def _text(fdp: atheris.FuzzedDataProvider, choices: tuple[str, ...]) -> str:
    """Pick a known value or fuzzed text, often a known value with a fuzzed tail."""
    match fdp.ConsumeIntInRange(0, 2):
        case 0:
            return fdp.PickValueInList(list(choices))
        case 1:
            return fdp.PickValueInList(list(choices)) + fdp.ConsumeUnicodeNoSurrogates(_MAX_TEXT)
        case _:
            return fdp.ConsumeUnicodeNoSurrogates(_MAX_TEXT)


def _json_value(fdp: atheris.FuzzedDataProvider) -> Any:  # noqa: ANN401 - any JSON value
    match fdp.ConsumeIntInRange(0, 5):
        case 0:
            return fdp.ConsumeUnicodeNoSurrogates(_MAX_TEXT)
        case 1:
            return fdp.ConsumeInt(8)
        case 2:
            return fdp.ConsumeRegularFloat()
        case 3:
            return fdp.ConsumeBool()
        case 4:
            return None
        case _:
            return [fdp.ConsumeUnicodeNoSurrogates(8) for _ in range(fdp.ConsumeIntInRange(0, 3))]


def _structured_frame(fdp: atheris.FuzzedDataProvider) -> str:
    """Build a command-shaped frame so most inputs get past the JSON and type checks."""
    msg: dict[str, Any] = {"type": _text(fdp, _TYPES)}
    if fdp.ConsumeBool():
        msg["id"] = fdp.ConsumeUnicodeNoSurrogates(_MAX_TEXT) if fdp.ConsumeBool() else _json_value(fdp)
    if fdp.ConsumeBool():
        msg["method"] = _text(fdp, _METHODS)
    if fdp.ConsumeBool():
        msg["path"] = _text(fdp, _PATH_STEMS)
    if fdp.ConsumeBool():
        msg["params"] = {
            fdp.ConsumeUnicodeNoSurrogates(16): _json_value(fdp)
            for _ in range(fdp.ConsumeIntInRange(0, _MAX_KEY_COUNT))
        }
    if fdp.ConsumeBool():
        msg["headers"] = {
            _text(fdp, _HEADER_NAMES): _json_value(fdp) if fdp.ConsumeBool() else fdp.ConsumeUnicodeNoSurrogates(32)
            for _ in range(fdp.ConsumeIntInRange(0, _MAX_KEY_COUNT))
        }
    if fdp.ConsumeBool():
        msg["body"] = {fdp.ConsumeUnicodeNoSurrogates(16): _json_value(fdp) for _ in range(fdp.ConsumeIntInRange(0, 3))}
    if fdp.ConsumeBool():
        msg[fdp.ConsumeUnicodeNoSurrogates(16)] = _json_value(fdp)
    return json.dumps(msg)


def _frame(data: bytes) -> str | bytes:
    fdp = atheris.FuzzedDataProvider(data)
    match fdp.ConsumeIntInRange(0, 3):
        case 0:
            return fdp.ConsumeBytes(fdp.remaining_bytes())
        case 1:
            return fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
        case _:
            return _structured_frame(fdp)


def _check_seam_helpers(frame: str | bytes) -> bool:
    """Drive the parsers directly, so a failure names the helper and not the task.

    Returns whether the frame is a valid command that the allowlist accepts.
    """
    if isinstance(frame, bytes):
        return False
    try:
        msg = json.loads(frame)
    except (ValueError, RecursionError):
        return False
    if not isinstance(msg, dict):
        return False

    safe = extract_safe_relay_headers(msg.get("headers"))
    if not set(safe) <= _TRACE_HEADERS:
        msg_ = f"header filter let through {sorted(safe)}"
        raise AssertionError(msg_)

    try:
        envelope = RelayCommandEnvelope.model_validate(msg)
    except ValidationError:
        return False
    if not set(extract_safe_relay_headers(envelope.headers)) <= _TRACE_HEADERS:
        msg_ = "header filter let through a non-trace header from a valid envelope"
        raise AssertionError(msg_)
    return relay_command_is_allowed(envelope.method.upper(), envelope.path)


class _Harness:
    """Shared event loop and client, reused across inputs to keep runs fast."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.probe = _RouteProbe()
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.probe, raise_app_exceptions=False),
            base_url="http://127.0.0.1:8018",
        )

    def run(self, frame: str | bytes, *, allowed: bool) -> None:
        self.probe.requests = 0
        self.probe.dispatched.clear()
        self.loop.run_until_complete(self._one_frame(frame))
        # The sent path can differ from the checked one, since httpx moves a `?` or
        # `#` tail out of the path. So the route check below is the real guard.
        if self.probe.requests and not allowed:
            msg = f"dispatched a command the allowlist rejects: {frame!r}"
            raise AssertionError(msg)
        for method, raw_path, route in self.probe.dispatched:
            if not _route_is_allowlisted(method, route):
                msg = f"allowlisted {method} {raw_path!r} routed to {route.path!r}"
                raise AssertionError(msg)

    async def _one_frame(self, frame: str | bytes) -> None:
        pending: set[asyncio.Task[None]] = set()
        failures: list[BaseException] = []

        def _on_task_done(task: asyncio.Task[None]) -> None:
            pending.discard(task)
            if not task.cancelled() and (exc := task.exception()) is not None:
                failures.append(exc)

        await _handle_relay_message(
            _FakeWebSocket(),  # ty: ignore[invalid-argument-type]
            self.http,
            frame,
            pending,
            _on_task_done,
            asyncio.Semaphore(4),
            asyncio.Lock(),
            relay_state=RelayRuntimeState(),
            max_pending_commands=8,
        )
        await asyncio.gather(*pending, return_exceptions=True)
        if failures:
            raise failures[0]


_HARNESS: _Harness | None = None


def test_one_input(data: bytes) -> None:
    """Feed one fuzz input to the relay seam."""
    global _HARNESS  # noqa: PLW0603 - built once, after atheris has parsed its flags
    if _HARNESS is None:
        _HARNESS = _Harness()
    frame = _frame(data)
    _HARNESS.run(frame, allowed=_check_seam_helpers(frame))


def main() -> None:
    """Run the fuzzer with libFuzzer flags from the command line."""
    # The seam logs a warning per rejected frame, which would drown the fuzzer output.
    logging.disable(logging.CRITICAL)
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
