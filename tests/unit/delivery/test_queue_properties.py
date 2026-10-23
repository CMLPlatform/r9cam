"""Stateful property test for the upload queue's bookkeeping."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule
from PIL import Image
from pydantic import AnyUrl

from app.delivery import queue as upload_queue_mod
from app.delivery.base import ImageSink, ImageSinkError, StoredImage
from app.delivery.queue import _MAX_ATTEMPTS, QueuedCapture, UploadQueue, UploadQueueFullError, _metadata_payload
from tests.constants import EXAMPLE_IMAGE_URL

if TYPE_CHECKING:
    from collections.abc import Coroutine


def _jpeg(size: int, seed: int) -> bytes:
    buffer = BytesIO()
    Image.effect_noise((size, size), 64 + seed).convert("RGB").save(buffer, format="JPEG")
    return buffer.getvalue()


# A few real JPEGs of different sizes, so the byte cap is hit at different points.
_JPEGS = tuple(_jpeg(size, seed) for seed, size in enumerate((4, 8, 16, 24)))
_START = datetime(2026, 1, 1, tzinfo=UTC)


def _entry_bytes(jpeg: bytes) -> int:
    """Bytes one fresh queue entry takes on disk, sidecar included."""
    payload = _metadata_payload(
        image_id="0" * 32,
        capture_metadata={"width": 8},
        upload_metadata={"product_id": 0},
        attempts=0,
        next_attempt_at=_START,
    )
    return len(jpeg) + len(json.dumps(payload, indent=2).encode())


class _Clock:
    """Stands in for ``datetime`` inside the queue module, so backoff can elapse without sleeping."""

    current = _START

    @classmethod
    def now(cls, tz: object = None) -> datetime:
        del tz
        return cls.current

    @staticmethod
    def fromisoformat(value: str) -> datetime:
        return datetime.fromisoformat(value)


class _RecordingSink:
    """Sink that fails on demand and records every capture it accepted."""

    def __init__(self) -> None:
        self.fail = False
        self.delivered: list[str] = []

    async def put(self, *, image_id: str, **_kwargs: object) -> StoredImage:
        if self.fail:
            msg = "sink is down"
            raise ImageSinkError(msg)
        self.delivered.append(image_id)
        return StoredImage(image_id=f"srv-{image_id}", image_url=AnyUrl(EXAMPLE_IMAGE_URL))


class UploadQueueMachine(RuleBasedStateMachine):
    """Every capture handed to the queue ends up in exactly one known place."""

    def __init__(self) -> None:
        super().__init__()
        self.workdir = Path(tempfile.mkdtemp(prefix="queue-property-"))
        self.root = self.workdir / "queue"
        self.loop = asyncio.new_event_loop()
        self.clock_patch = patch.object(upload_queue_mod, "datetime", _Clock)
        self.clock_patch.start()
        _Clock.current = _START
        self.sink = _RecordingSink()
        self.next_seed = 0
        self.accepted: set[str] = set()
        self.rejected_sources: list[Path] = []
        self.dead_lettered: set[str] = set()
        self.manually_delivered: list[str] = []

    # The cap is a whole number of entries plus a little slack, so the queue can be filled to the byte.
    @initialize(
        jpeg=st.sampled_from(_JPEGS),
        slots=st.integers(min_value=0, max_value=3),
        slack=st.integers(min_value=0, max_value=8),
        dead_max_entries=st.none() | st.integers(min_value=0, max_value=3),
    )
    def make_queue(self, jpeg: bytes, slots: int, slack: int, dead_max_entries: int | None) -> None:
        """Build a queue with a byte cap and a dead-letter retention limit."""
        self.jpeg = jpeg
        self.max_pending_bytes = slots * _entry_bytes(jpeg) + slack
        self.dead_max_entries = dead_max_entries
        self.queue = UploadQueue(
            self.root,
            sink=cast("ImageSink", self.sink),
            max_pending_bytes=self.max_pending_bytes,
            dead_max_entries=dead_max_entries,
        )

    def teardown(self) -> None:
        """Restore the real clock and remove the queue directory."""
        self.clock_patch.stop()
        self.loop.close()
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _run[T](self, coro: Coroutine[object, object, T]) -> T:
        return self.loop.run_until_complete(coro)

    def _note_failure(self, entry: QueuedCapture) -> None:
        if entry.attempts + 1 >= _MAX_ATTEMPTS:
            self.dead_lettered.add(entry.image_id)

    def _ids_in(self, directory: Path) -> set[str]:
        return {path.stem for path in directory.glob("*.jpg")}

    # ── Rules ─────────────────────────────────────────────────────────────

    @rule(product_id=st.integers(min_value=0, max_value=9))
    def enqueue(self, product_id: int) -> None:
        """Hand the queue a new capture, as ``capture_jpeg`` does when a push fails."""
        image_id = f"{self.next_seed:032x}"
        self.next_seed += 1
        source = self.workdir / f"capture-{image_id}.jpg"
        source.write_bytes(self.jpeg)
        try:
            self._run(
                self.queue.enqueue(
                    image_id=image_id,
                    image_path=source,
                    capture_metadata={"width": 8},
                    upload_metadata={"product_id": product_id},
                )
            )
        except UploadQueueFullError:
            self.rejected_sources.append(source)
        else:
            self.accepted.add(image_id)

    @precondition(lambda self: self._ids_in(self.root))
    @rule(data=st.data())
    def mark_attempt_failed(self, data: st.DataObject) -> None:
        """Record a failed upload for one pending capture."""
        entry = data.draw(st.sampled_from(self.queue.iter_pending()))
        self._note_failure(entry)
        self._run(self.queue.mark_attempt_failed(entry, reason="property test"))

    @precondition(lambda self: self._ids_in(self.root))
    @rule(data=st.data())
    def mark_attempt_succeeded(self, data: st.DataObject) -> None:
        """Record a successful upload for one pending capture."""
        entry = data.draw(st.sampled_from(self.queue.iter_pending()))
        self._run(self.queue.mark_attempt_succeeded(entry))
        self.manually_delivered.append(entry.image_id)

    @rule(sink_fails=st.booleans())
    def drain_once(self, *, sink_fails: bool) -> None:
        """Run one drain pass against a sink that is either up or down."""
        self.sink.fail = sink_fails
        if sink_fails:
            for entry in self.queue.iter_pending():
                if self.queue.is_due(entry):
                    self._note_failure(entry)
        before = len(self.sink.delivered)
        successes = self._run(self.queue.drain_once())
        assert successes == len(self.sink.delivered) - before

    @rule()
    def prune_dead_letters(self) -> None:
        """Apply dead-letter retention."""
        self._run(self.queue.prune_dead_letters())

    # A whole-second time serialises shorter than one with microseconds, so both need to come up often.
    @rule(seconds=st.integers(min_value=0, max_value=3 * 60 * 60), microsecond=st.sampled_from((0, 250_000)))
    def advance_clock(self, seconds: int, microsecond: int) -> None:
        """Let time pass so backoff can elapse."""
        _Clock.current = (_Clock.current + timedelta(seconds=seconds)).replace(microsecond=microsecond)

    # ── Invariants ────────────────────────────────────────────────────────

    @invariant()
    def every_capture_is_in_exactly_one_place(self) -> None:
        """Each accepted capture is pending, dead, delivered once, or pruned from dead letters."""
        pending = self._ids_in(self.root)
        dead = self._ids_in(self.root / "dead")
        delivered = [*self.sink.delivered, *self.manually_delivered]

        assert len(delivered) == len(set(delivered)), "a capture was delivered twice"
        places = [pending, dead, set(delivered)]
        assert sum(len(place) for place in places) == len(set().union(*places)), "a capture is in two places"
        assert set().union(*places) <= self.accepted

        # Dead-letter retention is the only path allowed to delete a capture.
        gone = self.accepted - set().union(*places)
        assert gone <= self.dead_lettered, "a capture was lost"
        if gone:
            assert self.dead_max_entries is not None
        if self.dead_max_entries is not None:
            assert len(dead) <= self.dead_max_entries
        for source in self.rejected_sources:
            assert source.exists(), "a rejected capture lost its source file"

    @invariant()
    def pending_entries_have_both_files(self) -> None:
        """Every pending JPEG has its sidecar and the other way round."""
        jpgs = {path.stem for path in self.root.glob("*.jpg")}
        sidecars = {path.stem for path in self.root.glob("*.json")}
        assert jpgs == sidecars

    @invariant()
    def pending_bytes_stay_under_the_cap(self) -> None:
        """The queue directory never holds more bytes than the cap allows."""
        used = sum(path.stat().st_size for pattern in ("*.jpg", "*.json") for path in self.root.glob(pattern))
        assert used <= self.max_pending_bytes


UploadQueueMachine.TestCase.settings = settings(max_examples=25, deadline=None, stateful_step_count=30)
test_property_upload_queue_never_loses_or_duplicates_captures = UploadQueueMachine.TestCase
