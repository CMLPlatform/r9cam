"""Async task utilities."""

import asyncio
import contextlib
from collections.abc import Awaitable


async def finish_before_cancel[T](awaitable: Awaitable[T]) -> T:
    """Await a thread call; on cancel, wait for the thread to return before re-raising.

    A cancel cannot stop the thread, so whoever cleans up after it must not run alongside it.
    Pass a future to read its outcome after a cancel.
    """
    future = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait({future})
        raise
