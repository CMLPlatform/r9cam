"""Tests for the async task utilities."""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.utils.tasks import finish_before_cancel


async def test_cancel_waits_for_the_thread_before_reraising() -> None:
    """Two cancels in a row still wait for the thread, then raise CancelledError."""
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def work() -> None:
        started.set()
        release.wait(timeout=5)
        finished.set()

    task = asyncio.create_task(finish_before_cancel(asyncio.to_thread(work)))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
