"""Tests for the upload queue."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import AnyUrl

from app.delivery import queue as upload_queue_mod
from app.delivery.base import ImageSink, ImageSinkError, StoredImage
from app.delivery.queue import UploadQueue, run_upload_queue_worker
from tests.constants import EXAMPLE_IMAGE_URL


def image_id(seed: int) -> str:
    """Return a generated capture ID-shaped test value."""
    return f"{seed:032x}"


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="green").save(buffer, format="JPEG")
    return buffer.getvalue()


if TYPE_CHECKING:
    from pathlib import Path


class _FakeSink:
    """Minimal ``ImageSink`` stub — returns a fixed ``StoredImage`` on every ``put``."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.put = AsyncMock(side_effect=self._put)

    async def _put(self, **_kwargs: object) -> StoredImage:
        if self._fail:
            msg = "fake sink is failing"
            raise ImageSinkError(msg)
        return StoredImage(image_id="srv-1", image_url=AnyUrl(EXAMPLE_IMAGE_URL))


@pytest.fixture
def queue_root(tmp_path: Path) -> Path:
    """A clean upload-queue root directory."""
    return tmp_path / "queue"


@pytest.fixture
def sink() -> _FakeSink:
    """A happy-path sink that always succeeds."""
    return _FakeSink(fail=False)


@pytest.fixture
def failing_sink() -> _FakeSink:
    """A sink that always raises ``ImageSinkError``."""
    return _FakeSink(fail=True)


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """A small fake JPEG file outside the queue root."""
    path = tmp_path / "capture.jpg"
    path.write_bytes(_jpeg_bytes())
    return path


class TestEnqueue:
    """Tests for UploadQueue.enqueue."""

    async def test_moves_file_and_writes_metadata(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
    ) -> None:
        """Enqueue should move the jpg into the queue root and write a metadata sidecar."""
        capture_id = image_id(1)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        entry = await queue.enqueue(
            image_id=capture_id,
            image_path=sample_image,
            capture_metadata={"width": 1920},
            upload_metadata={"product_id": 42},
        )

        assert not await asyncio.to_thread(sample_image.exists)
        assert entry.image_path == queue_root / f"{capture_id}.jpg"
        assert entry.metadata_path == queue_root / f"{capture_id}.json"
        assert await asyncio.to_thread(entry.image_path.exists)
        assert await asyncio.to_thread(entry.metadata_path.exists)
        assert queue.is_due(entry)

    async def test_creates_queue_and_dead_directories(
        self,
        queue_root: Path,
        sink: _FakeSink,
    ) -> None:
        """Instantiating the queue should create the root, its missing parents and the dead-letter subdir."""
        assert not await asyncio.to_thread(queue_root.exists)
        UploadQueue(queue_root / "data" / "queue", sink=cast("ImageSink", sink))
        assert await asyncio.to_thread((queue_root / "data" / "queue").is_dir)
        assert await asyncio.to_thread((queue_root / "data" / "queue" / "dead").is_dir)

    async def test_rejects_enqueue_when_pending_entry_limit_is_reached(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
    ) -> None:
        """Queue capacity should prevent unbounded pending entries."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), max_pending_entries=0)
        capture_id = image_id(1)

        with pytest.raises(upload_queue_mod.UploadQueueFullError):
            await queue.enqueue(
                image_id=capture_id,
                image_path=sample_image,
                capture_metadata={},
                upload_metadata={},
            )

        assert await asyncio.to_thread(sample_image.exists)

    async def test_failed_attempt_does_not_push_queue_past_byte_limit(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A capture enqueued on a whole second must not grow its sidecar when a retry is scheduled."""
        clock = [datetime(2026, 1, 1, tzinfo=UTC)]

        class _Clock:
            @staticmethod
            def now(tz: object = None) -> datetime:
                del tz
                return clock[0]

            fromisoformat = staticmethod(datetime.fromisoformat)

        monkeypatch.setattr(upload_queue_mod, "datetime", _Clock)
        capture_id = image_id(1)
        payload = upload_queue_mod._metadata_payload(
            image_id=capture_id, capture_metadata={}, upload_metadata={}, attempts=0, next_attempt_at=clock[0]
        )
        image_bytes = (await asyncio.to_thread(sample_image.stat)).st_size
        limit = image_bytes + len(upload_queue_mod.json.dumps(payload, indent=2).encode())
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), max_pending_bytes=limit)
        entry = await queue.enqueue(
            image_id=capture_id, image_path=sample_image, capture_metadata={}, upload_metadata={}
        )

        clock[0] += timedelta(microseconds=250_000)
        await queue.mark_attempt_failed(entry)

        assert upload_queue_mod._directory_bytes(queue_root) <= limit

    async def test_concurrent_enqueues_respect_byte_limit(
        self,
        queue_root: Path,
        tmp_path: Path,
        sink: _FakeSink,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With room for exactly one capture, two simultaneous enqueues admit one and reject one."""
        second_image = tmp_path / "second.jpg"
        second_image.write_bytes(_jpeg_bytes())
        first_image = tmp_path / "first.jpg"
        first_image.write_bytes(_jpeg_bytes())
        payload = upload_queue_mod._metadata_payload(
            image_id=image_id(1), capture_metadata={}, upload_metadata={}, attempts=0, next_attempt_at=datetime.now(UTC)
        )
        limit = len(_jpeg_bytes()) + len(upload_queue_mod.json.dumps(payload, indent=2).encode())
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), max_pending_bytes=limit)
        real_move = upload_queue_mod.shutil.move

        def slow_move(src: str, dst: str) -> object:
            # Holds the first move open so the second enqueue's capacity check runs before it lands.
            time.sleep(0.2)
            return real_move(src, dst)

        monkeypatch.setattr(upload_queue_mod.shutil, "move", slow_move)

        results = await asyncio.gather(
            *(
                queue.enqueue(image_id=image_id(n), image_path=path, capture_metadata={}, upload_metadata={})
                for n, path in ((1, first_image), (2, second_image))
            ),
            return_exceptions=True,
        )

        assert sum(isinstance(r, upload_queue_mod.UploadQueueFullError) for r in results) == 1
        assert upload_queue_mod._directory_bytes(queue_root) <= limit

    async def test_queue_already_over_limit_on_disk_rejects_new_captures(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
    ) -> None:
        """Bytes already on disk at startup count against the cap."""
        await asyncio.to_thread(queue_root.mkdir, parents=True)
        await asyncio.to_thread((queue_root / f"{image_id(9)}.jpg").write_bytes, b"x" * 1000)

        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), max_pending_bytes=500)

        with pytest.raises(upload_queue_mod.UploadQueueFullError):
            await queue.enqueue(image_id=image_id(1), image_path=sample_image, capture_metadata={}, upload_metadata={})

    async def test_old_image_without_sidecar_does_not_fill_byte_cap(
        self, queue_root: Path, sample_image: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A jpg orphaned by a crash before its sidecar was written stops counting against the cap."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), max_pending_bytes=2 * len(_jpeg_bytes()))
        (queue_root / f"{image_id(1)}.jpg").write_bytes(_jpeg_bytes() * 2)
        monkeypatch.setattr(upload_queue_mod, "_ORPHAN_IMAGE_GRACE_SECONDS", -1)

        await queue.enqueue(image_id=image_id(2), image_path=sample_image, capture_metadata={}, upload_metadata={})

        assert [e.image_id for e in queue.iter_pending()] == [image_id(2)]


class TestIterPending:
    """Tests for iter_pending ordering + resilience."""

    async def test_returns_entries_sorted_by_next_attempt(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
    ) -> None:
        """Entries with earlier next_attempt_at should come first."""
        first_id = image_id(1)
        second_id = image_id(2)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))

        # Enqueue one entry that's due now.
        await queue.enqueue(
            image_id=first_id,
            image_path=sample_image,
            capture_metadata={},
            upload_metadata={},
        )

        # Manually add a second entry dated in the future.
        future = datetime.now(UTC) + timedelta(hours=1)
        image_b = queue_root / f"{second_id}.jpg"
        image_b.write_bytes(_jpeg_bytes())
        (queue_root / f"{second_id}.json").write_text(
            f'{{"image_id": "{second_id}", "capture_metadata": {{}}, "upload_metadata": {{}}, '
            f'"attempts": 1, "next_attempt_at": "{future.isoformat()}"}}'
        )

        entries = queue.iter_pending()
        assert [e.image_id for e in entries] == [first_id, second_id]

    def test_skips_orphan_metadata(self, queue_root: Path, sink: _FakeSink) -> None:
        """A .json without a matching .jpg should be cleaned up, not yielded."""
        capture_id = image_id(1)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        orphan = queue_root / f"{capture_id}.json"
        orphan.write_text(f'{{"image_id": "{capture_id}"}}')
        assert queue.iter_pending() == []
        assert not orphan.exists()

    def test_uses_metadata_path_stem_as_authoritative_image_id(self, queue_root: Path, sink: _FakeSink) -> None:
        """Queue metadata path controls the generated capture id."""
        capture_id = image_id(1)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        metadata_path = queue_root / f"{capture_id}.json"
        image_path = queue_root / f"{capture_id}.jpg"
        image_path.write_bytes(_jpeg_bytes())
        metadata_path.write_text(f'{{"image_id": "{image_id(2)}"}}')

        entries = queue.iter_pending()

        assert len(entries) == 1
        assert entries[0].image_id == capture_id

    def test_ignores_hostile_sidecar_filename(self, queue_root: Path, sink: _FakeSink) -> None:
        """Sidecar metadata must not control the queued file path or upload filename."""
        capture_id = image_id(12)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        metadata_path = queue_root / f"{capture_id}.json"
        image_path = queue_root / f"{capture_id}.jpg"
        image_path.write_bytes(_jpeg_bytes())
        metadata_path.write_text(f'{{"image_id": "{capture_id}", "filename": "../../escape.bin"}}')

        entries = queue.iter_pending()

        assert len(entries) == 1
        assert entries[0].image_path == image_path

    def test_skips_unreadable_metadata_without_dropping_siblings(self, queue_root: Path, sink: _FakeSink) -> None:
        """A truncated sidecar must not poison the whole drain pass."""
        good_id, corrupt_id = image_id(1), image_id(2)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        for capture_id in (good_id, corrupt_id):
            (queue_root / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / f"{good_id}.json").write_text(f'{{"image_id": "{good_id}"}}')
        (queue_root / f"{corrupt_id}.json").write_text('{"image_id": ')

        entries = queue.iter_pending()

        assert [e.image_id for e in entries] == [good_id]
        # Left in place: unreadable is not the same as invalid, so a human can inspect it.
        assert (queue_root / f"{corrupt_id}.json").exists()

    @pytest.mark.parametrize(
        "sidecar",
        [
            "[]",
            "null",
            '{"attempts": null}',
            '{"attempts": "two"}',
            '{"attempts": Infinity}',
            '{"capture_metadata": []}',
            '{"upload_metadata": "x"}',
        ],
    )
    def test_skips_sidecar_of_the_wrong_shape(self, queue_root: Path, sink: _FakeSink, sidecar: str) -> None:
        """Valid JSON of the wrong shape is skipped like a truncated sidecar, not raised."""
        good_id, bad_id = image_id(1), image_id(2)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        for capture_id in (good_id, bad_id):
            (queue_root / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / f"{good_id}.json").write_text(f'{{"image_id": "{good_id}"}}')
        (queue_root / f"{bad_id}.json").write_text(sidecar)

        entries = queue.iter_pending()

        assert [e.image_id for e in entries] == [good_id]
        assert (queue_root / f"{bad_id}.json").exists()

    @pytest.mark.parametrize(("sidecar", "attempts"), [("{}", 0), ('{"attempts": -3}', 0), ('{"attempts": 2}', 2)])
    def test_reads_attempts(self, queue_root: Path, sink: _FakeSink, sidecar: str, attempts: int) -> None:
        """A missing attempt count is zero, and a negative one cannot index past the backoff schedule."""
        capture_id = image_id(1)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        (queue_root / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / f"{capture_id}.json").write_text(sidecar)

        [entry] = queue.iter_pending()

        assert entry.attempts == attempts

    def test_reads_naive_timestamp_as_utc(self, queue_root: Path, sink: _FakeSink) -> None:
        """A next_attempt_at without a timezone is read as UTC, so entries still sort and compare."""
        naive_id, aware_id = image_id(1), image_id(2)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        for capture_id in (naive_id, aware_id):
            (queue_root / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / f"{naive_id}.json").write_text('{"next_attempt_at": "2020-01-01T00:00:00"}')
        (queue_root / f"{aware_id}.json").write_text('{"next_attempt_at": "2021-01-01T00:00:00+00:00"}')

        entries = queue.iter_pending()

        assert [e.image_id for e in entries] == [naive_id, aware_id]
        assert entries[0].next_attempt_at == datetime(2020, 1, 1, tzinfo=UTC)
        assert queue.is_due(entries[0])

    def test_removes_old_image_without_sidecar(
        self, queue_root: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A jpg left without a sidecar by a crash is removed once the grace period has passed."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        orphan = queue_root / f"{image_id(1)}.jpg"
        orphan.write_bytes(_jpeg_bytes())
        monkeypatch.setattr(upload_queue_mod, "_ORPHAN_IMAGE_GRACE_SECONDS", -1)

        assert queue.iter_pending() == []
        assert not orphan.exists()

    def test_keeps_new_image_without_sidecar(self, queue_root: Path, sink: _FakeSink) -> None:
        """A jpg whose sidecar is still being written must not be touched."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        in_flight = queue_root / f"{image_id(1)}.jpg"
        in_flight.write_bytes(_jpeg_bytes())

        assert queue.iter_pending() == []
        assert in_flight.exists()

    def test_cleans_up_metadata_with_invalid_image_id(self, queue_root: Path, sink: _FakeSink) -> None:
        """A sidecar whose stem is not a valid capture id can never be uploaded, so it is removed."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        metadata_path = queue_root / "not-a-capture-id.json"
        image_path = queue_root / "not-a-capture-id.jpg"
        image_path.write_bytes(_jpeg_bytes())
        metadata_path.write_text('{"image_id": "not-a-capture-id"}')

        assert queue.iter_pending() == []
        assert not metadata_path.exists()
        assert not image_path.exists()

    def test_orphan_sweep_handles_every_kind_of_image_in_one_pass(
        self, queue_root: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each image the sweep skips or cannot remove leaves the later ones to it."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        (queue_root / f"{image_id(1)}.jpg").symlink_to(queue_root / "gone.jpg")
        (queue_root / f"{image_id(2)}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / f"{image_id(2)}.json").write_text("{}")
        (queue_root / f"{image_id(3)}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / "dead" / f"{image_id(3)}.json").write_text('{"capture_metadata": {}, "upload_metadata": {}}')
        (queue_root / f"{image_id(4)}.jpg").mkdir()
        orphan = queue_root / f"{image_id(5)}.jpg"
        orphan.write_bytes(_jpeg_bytes())
        later = time.time() + 120
        monkeypatch.setattr(upload_queue_mod.time, "time", lambda: later)

        pending = queue.iter_pending()

        assert sorted(e.image_id for e in pending) == [image_id(2), image_id(3)]
        assert not orphan.exists()

    def test_orphan_sweep_continues_past_a_new_image(
        self, queue_root: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A jpg still inside the grace period does not stop the sweep of older ones."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        old = queue_root / f"{image_id(2)}.jpg"
        old.write_bytes(_jpeg_bytes())
        new = queue_root / f"{image_id(1)}.jpg"
        while True:
            new.write_bytes(_jpeg_bytes())
            if new.stat().st_ctime > old.stat().st_ctime:
                break
        new_ctime = new.stat().st_ctime
        monkeypatch.setattr(upload_queue_mod, "_ORPHAN_IMAGE_GRACE_SECONDS", 0)
        monkeypatch.setattr(upload_queue_mod.time, "time", lambda: new_ctime)

        assert queue.iter_pending() == []
        assert new.exists()
        assert not old.exists()

    def test_failed_dead_letter_finish_is_left_for_later(
        self, queue_root: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OSError while moving a cut-off dead letter's sidecar does not break the scan."""
        capture_id = image_id(1)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        (queue_root / "dead" / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / f"{capture_id}.json").write_text("{}")
        later = time.time() + 120
        monkeypatch.setattr(upload_queue_mod.time, "time", lambda: later)

        def _full_disk(_src: str, _dst: str) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(upload_queue_mod.shutil, "move", _full_disk)

        assert queue.iter_pending() == []
        assert (queue_root / f"{capture_id}.json").exists()


class TestDrainOnce:
    """Tests for drain_once happy-path and failure-path."""

    async def test_successful_drain_removes_entry(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
    ) -> None:
        """When the sink succeeds, the queue entry should be deleted."""
        capture_id = image_id(3)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        entry = await queue.enqueue(
            image_id=capture_id,
            image_path=sample_image,
            capture_metadata={},
            upload_metadata={"product_id": 1},
        )

        successes = await queue.drain_once()

        assert successes == 1
        assert sink.put.await_count == 1
        assert sink.put.await_args is not None
        assert sink.put.await_args.kwargs["filename"] == f"{capture_id}.jpg"
        assert not await asyncio.to_thread(entry.image_path.exists)
        assert not await asyncio.to_thread(entry.metadata_path.exists)

    async def test_drain_counts_every_success(
        self,
        queue_root: Path,
        sample_image: Path,
        tmp_path: Path,
        sink: _FakeSink,
    ) -> None:
        """Two entries that both upload should be counted as two successes."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        second_image = tmp_path / "capture-2.jpg"
        await asyncio.to_thread(second_image.write_bytes, _jpeg_bytes())
        for capture_id, path in ((image_id(21), sample_image), (image_id(22), second_image)):
            await queue.enqueue(image_id=capture_id, image_path=path, capture_metadata={}, upload_metadata={})

        successes = await queue.drain_once()

        assert successes == 2
        assert sink.put.await_count == 2
        assert queue.iter_pending() == []

    async def test_failed_drain_increments_attempts(
        self,
        queue_root: Path,
        sample_image: Path,
        failing_sink: _FakeSink,
    ) -> None:
        """A failed sink put should bump attempts and schedule a later retry."""
        capture_id = image_id(4)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", failing_sink))
        entry = await queue.enqueue(
            image_id=capture_id,
            image_path=sample_image,
            capture_metadata={},
            upload_metadata={},
        )

        successes = await queue.drain_once()

        assert successes == 0
        assert failing_sink.put.await_count == 1
        assert await asyncio.to_thread(entry.image_path.exists)  # still present
        reloaded = queue.iter_pending()[0]
        assert reloaded.attempts == 1
        assert reloaded.next_attempt_at > datetime.now(UTC)

    async def test_timeout_error_increments_attempts(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
    ) -> None:
        """Upload timeouts should count as a failed attempt, not kill the drain."""
        capture_id = image_id(5)
        sink.put.side_effect = asyncio.TimeoutError
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        entry = await queue.enqueue(
            image_id=capture_id,
            image_path=sample_image,
            capture_metadata={},
            upload_metadata={},
        )

        successes = await queue.drain_once()

        assert successes == 0
        assert sink.put.await_count == 1
        assert await asyncio.to_thread(entry.image_path.exists)
        reloaded = queue.iter_pending()[0]
        assert reloaded.attempts == 1

    async def test_unexpected_sink_error_marks_failed_and_continues(
        self,
        queue_root: Path,
        tmp_path: Path,
        sink: _FakeSink,
    ) -> None:
        """One poisoned entry should not stop later due entries from draining."""
        bad_id = image_id(6)
        good_id = image_id(7)

        async def _put(**kwargs: object) -> StoredImage:
            if kwargs["image_id"] == bad_id:
                msg = "boom"
                raise ValueError(msg)
            return StoredImage(image_id="srv-1", image_url=AnyUrl(EXAMPLE_IMAGE_URL))

        sink.put.side_effect = _put
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))

        bad_image = tmp_path / f"{bad_id}.jpg"
        bad_image.write_bytes(_jpeg_bytes())
        good_image = tmp_path / f"{good_id}.jpg"
        good_image.write_bytes(_jpeg_bytes())

        bad_entry = await queue.enqueue(
            image_id=bad_id,
            image_path=bad_image,
            capture_metadata={},
            upload_metadata={},
        )
        good_entry = await queue.enqueue(
            image_id=good_id,
            image_path=good_image,
            capture_metadata={},
            upload_metadata={},
        )

        successes = await queue.drain_once()

        assert successes == 1
        assert sink.put.await_count == 2
        assert await asyncio.to_thread(bad_entry.image_path.exists)
        assert not await asyncio.to_thread(good_entry.image_path.exists)
        reloaded = {entry.image_id: entry for entry in queue.iter_pending()}
        assert reloaded[bad_id].attempts == 1

    async def test_skips_entries_not_yet_due(
        self,
        queue_root: Path,
        sink: _FakeSink,
    ) -> None:
        """Entries with next_attempt_at in the future must be ignored this pass."""
        capture_id = image_id(8)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        future = datetime.now(UTC) + timedelta(hours=1)
        (queue_root / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / f"{capture_id}.json").write_text(
            f'{{"image_id": "{capture_id}", "capture_metadata": {{}}, "upload_metadata": {{}}, '
            f'"attempts": 2, "next_attempt_at": "{future.isoformat()}"}}'
        )

        successes = await queue.drain_once()

        assert successes == 0
        assert sink.put.await_count == 0

    async def test_invalid_queued_media_marks_failed_without_upload(
        self,
        queue_root: Path,
        sink: _FakeSink,
    ) -> None:
        """Invalid queued media should fail through the retry path without reaching the sink."""
        capture_id = image_id(13)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        (queue_root / f"{capture_id}.jpg").write_bytes(b"not a jpeg")
        (queue_root / f"{capture_id}.json").write_text(
            f'{{"image_id": "{capture_id}", "capture_metadata": {{}}, "upload_metadata": {{}}, "attempts": 0, '
            f'"next_attempt_at": "{datetime.now(UTC).isoformat()}"}}'
        )

        successes = await queue.drain_once()

        assert successes == 0
        assert sink.put.await_count == 0
        assert queue.iter_pending()[0].attempts == 1


class TestDeadLetter:
    """Tests for exhausting retries and dead-lettering."""

    async def test_dead_letters_after_max_attempts(
        self,
        queue_root: Path,
        sample_image: Path,
        sink: _FakeSink,
    ) -> None:
        """After _MAX_ATTEMPTS consecutive failures the entry should move under dead/."""
        capture_id = image_id(9)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        entry = await queue.enqueue(
            image_id=capture_id,
            image_path=sample_image,
            capture_metadata={},
            upload_metadata={},
        )

        max_attempts = upload_queue_mod._MAX_ATTEMPTS
        # Simulate attempts 1..(max_attempts - 1) — not yet dead.
        current = entry
        for attempt in range(1, max_attempts):
            dead = await queue.mark_attempt_failed(current)
            assert dead is False
            refreshed = queue.iter_pending()
            assert len(refreshed) == 1
            assert refreshed[0].attempts == attempt
            current = refreshed[0]

        # One more failure — dead-letter.
        dead = await queue.mark_attempt_failed(current)
        assert dead is True
        assert queue.iter_pending() == []
        assert await asyncio.to_thread((queue_root / "dead" / f"{capture_id}.jpg").exists)
        assert await asyncio.to_thread((queue_root / "dead" / f"{capture_id}.json").exists)

    async def test_concurrent_iter_pending_keeps_entry_being_dead_lettered(
        self, queue_root: Path, sample_image: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scan between the jpg move and the sidecar move must not delete the sidecar."""
        capture_id = image_id(12)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        entry = await queue.enqueue(
            image_id=capture_id, image_path=sample_image, capture_metadata={}, upload_metadata={}
        )
        real_move = upload_queue_mod.shutil.move

        def move_then_scan(src: str, dst: str) -> object:
            moved = real_move(src, dst)
            if src.endswith(".jpg"):
                assert queue.iter_pending() == []
            return moved

        monkeypatch.setattr(upload_queue_mod.shutil, "move", move_then_scan)

        await queue._dead_letter(entry)

        assert sorted(p.name for p in (queue_root / "dead").iterdir()) == [f"{capture_id}.jpg", f"{capture_id}.json"]

    async def test_finishes_dead_letter_cut_off_after_image_move(
        self, queue_root: Path, sample_image: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A crash between the two moves leaves the jpg in dead/; a later scan moves its sidecar too."""
        capture_id = image_id(13)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        await queue.enqueue(image_id=capture_id, image_path=sample_image, capture_metadata={}, upload_metadata={})
        (queue_root / f"{capture_id}.jpg").rename(queue_root / "dead" / f"{capture_id}.jpg")

        assert queue.iter_pending() == []
        assert (queue_root / f"{capture_id}.json").exists()

        later = time.time() + 120
        monkeypatch.setattr(upload_queue_mod.time, "time", lambda: later)

        assert queue.iter_pending() == []
        assert sorted(p.name for p in (queue_root / "dead").iterdir()) == [f"{capture_id}.jpg", f"{capture_id}.json"]
        assert not await asyncio.to_thread((queue_root / f"{capture_id}.json").exists)

    async def test_prunes_oldest_dead_letters_over_count_limit(
        self,
        queue_root: Path,
        sink: _FakeSink,
    ) -> None:
        """Dead-letter retention should keep only the newest entries over count."""
        old_id = image_id(11)
        new_id = image_id(10)
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), dead_max_entries=1)
        for index, name in enumerate((old_id, new_id)):
            dead_image = queue_root / "dead" / f"{name}.jpg"
            dead_meta = queue_root / "dead" / f"{name}.json"
            dead_image.write_bytes(_jpeg_bytes())
            dead_meta.write_text("{}")
            mtime = (datetime.now(UTC) + timedelta(seconds=index)).timestamp()
            os.utime(dead_image, (mtime, mtime))
            os.utime(dead_meta, (mtime, mtime))

        await queue.prune_dead_letters()

        assert not (queue_root / "dead" / f"{old_id}.jpg").exists()
        assert not (queue_root / "dead" / f"{old_id}.json").exists()
        assert (queue_root / "dead" / f"{new_id}.jpg").exists()
        assert (queue_root / "dead" / f"{new_id}.json").exists()


class TestRequeueDead:
    """Tests for moving dead-lettered entries back after pairing."""

    @staticmethod
    async def _dead_letter(queue: UploadQueue, capture_id: str, source: Path) -> None:
        await asyncio.to_thread(source.write_bytes, _jpeg_bytes())
        entry = await queue.enqueue(
            image_id=capture_id, image_path=source, capture_metadata={"k": "v"}, upload_metadata={"u": "1"}
        )
        for _ in range(upload_queue_mod._MAX_ATTEMPTS):
            entry = queue.iter_pending()[0]
            await queue.mark_attempt_failed(entry)

    async def test_requeue_moves_entries_and_resets_attempts(
        self, queue_root: Path, tmp_path: Path, sink: _FakeSink
    ) -> None:
        """Dead entries return to the live queue, due now, with zero attempts."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        capture_id = image_id(20)
        await self._dead_letter(queue, capture_id, tmp_path / "a.jpg")
        assert queue.iter_pending() == []

        await queue.requeue_dead()

        [entry] = queue.iter_pending()
        assert entry.image_id == capture_id
        assert entry.attempts == 0
        assert entry.capture_metadata == {"k": "v"}
        assert entry.upload_metadata == {"u": "1"}
        assert queue.is_due(entry)
        assert list((queue_root / "dead").iterdir()) == []
        assert await queue.drain_once() == 1

    async def test_restart_finishes_requeue_interrupted_after_image_move(
        self, queue_root: Path, tmp_path: Path, sink: _FakeSink
    ) -> None:
        """A crash between the image move and the live sidecar write must not lose the capture."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        capture_id = image_id(30)
        await self._dead_letter(queue, capture_id, tmp_path / "c.jpg")
        (queue_root / "dead" / f"{capture_id}.jpg").rename(queue_root / f"{capture_id}.jpg")

        await queue.requeue_dead()

        [entry] = queue.iter_pending()
        assert entry.image_id == capture_id
        assert entry.attempts == 0
        assert entry.capture_metadata == {"k": "v"}
        assert list((queue_root / "dead").iterdir()) == []

    async def test_iter_pending_finishes_requeue_interrupted_after_image_move(
        self, queue_root: Path, tmp_path: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A restart that drains before any requeue recovers the half-moved capture, not deletes it."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        capture_id = image_id(31)
        await self._dead_letter(queue, capture_id, tmp_path / "d.jpg")
        (queue_root / "dead" / f"{capture_id}.jpg").rename(queue_root / f"{capture_id}.jpg")
        later = time.time() + 120
        monkeypatch.setattr(upload_queue_mod.time, "time", lambda: later)

        [entry] = queue.iter_pending()

        assert entry.image_id == capture_id
        assert entry.attempts == 0
        assert entry.capture_metadata == {"k": "v"}
        assert list((queue_root / "dead").iterdir()) == []

    async def test_failed_interrupted_requeue_does_not_stop_the_rest(
        self, queue_root: Path, tmp_path: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A full disk while finishing one half-moved capture leaves it for later and requeues the others."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        stuck, other = image_id(32), image_id(33)
        await self._dead_letter(queue, stuck, tmp_path / "e.jpg")
        await self._dead_letter(queue, other, tmp_path / "f.jpg")
        (queue_root / "dead" / f"{stuck}.jpg").rename(queue_root / f"{stuck}.jpg")
        real_write = upload_queue_mod.write_json_atomic

        def _write(path: Path, payload: dict[str, object]) -> None:
            if path.stem == stuck:
                raise OSError(28, "No space left on device")
            real_write(path, payload)

        monkeypatch.setattr(upload_queue_mod, "write_json_atomic", _write)

        await queue.requeue_dead()

        assert [e.image_id for e in queue.iter_pending()] == [other]
        assert (queue_root / "dead" / f"{stuck}.json").exists()
        assert (queue_root / f"{stuck}.jpg").exists()

    @pytest.mark.parametrize(
        ("sidecar", "capture", "upload"),
        [
            ('{"capture_metadata": [1], "upload_metadata": {"u": "1"}}', {}, {"u": "1"}),
            ('{"capture_metadata": {"k": "v"}, "upload_metadata": [2]}', {"k": "v"}, {}),
            ("not json", {}, {}),
        ],
    )
    async def test_interrupted_requeue_keeps_only_valid_metadata(
        self, queue_root: Path, sink: _FakeSink, sidecar: str, capture: dict[str, str], upload: dict[str, str]
    ) -> None:
        """A half-moved capture comes back even when its dead sidecar is damaged."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        capture_id = image_id(34)
        (queue_root / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / "dead" / f"{capture_id}.json").write_text(sidecar)

        await queue.requeue_dead()

        [entry] = queue.iter_pending()
        assert (entry.capture_metadata, entry.upload_metadata) == (capture, upload)

    async def test_dead_sidecar_without_any_image_is_dropped(self, queue_root: Path, sink: _FakeSink) -> None:
        """A dead sidecar whose image is gone everywhere is removed, and nothing goes live."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        (queue_root / "dead" / f"{image_id(35)}.json").write_text("{}")

        await queue.prune_dead_letters()

        assert list((queue_root / "dead").iterdir()) == []
        assert not await asyncio.to_thread((queue_root / f"{image_id(35)}.json").exists)

    async def test_requeue_fills_in_missing_metadata(self, queue_root: Path, sink: _FakeSink) -> None:
        """A dead sidecar without metadata keys still comes back, with empty metadata."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        (queue_root / "dead" / f"{image_id(36)}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / "dead" / f"{image_id(36)}.json").write_text("{}")

        await queue.requeue_dead()

        [entry] = queue.iter_pending()
        assert (entry.capture_metadata, entry.upload_metadata) == ({}, {})

    async def test_broken_dead_entry_does_not_stop_the_rest(self, queue_root: Path, sink: _FakeSink) -> None:
        """The oldest dead entry failing to requeue leaves the newer ones to go back."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        for index, (seed, sidecar) in enumerate(((37, "not json"), (38, "{}"))):
            dead_image = queue_root / "dead" / f"{image_id(seed)}.jpg"
            dead_meta = queue_root / "dead" / f"{image_id(seed)}.json"
            dead_image.write_bytes(_jpeg_bytes())
            dead_meta.write_text(sidecar)
            mtime = (datetime.now(UTC) + timedelta(seconds=index)).timestamp()
            os.utime(dead_image, (mtime, mtime))
            os.utime(dead_meta, (mtime, mtime))

        await queue.requeue_dead()

        assert [e.image_id for e in queue.iter_pending()] == [image_id(38)]

    async def test_requeue_counts_the_sidecar_against_the_byte_cap(self, queue_root: Path, sink: _FakeSink) -> None:
        """An entry whose jpg fits but whose new sidecar would not stays dead."""
        capture_id = image_id(39)
        (queue_root / "dead").mkdir(parents=True)
        (queue_root / "dead" / f"{capture_id}.jpg").write_bytes(_jpeg_bytes())
        (queue_root / "dead" / f"{capture_id}.json").write_text("{}")
        sidecar = upload_queue_mod._metadata_payload(
            image_id=capture_id, capture_metadata={}, upload_metadata={}, attempts=0, next_attempt_at=datetime.now(UTC)
        )
        cap = len(_jpeg_bytes()) + len(json.dumps(sidecar, indent=2).encode()) - 1
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), max_pending_bytes=cap)

        await queue.requeue_dead()

        assert queue.iter_pending() == []
        assert (queue_root / "dead" / f"{capture_id}.jpg").exists()

    async def test_requeue_honours_byte_cap(self, queue_root: Path, tmp_path: Path, sink: _FakeSink) -> None:
        """Entries that do not fit under the byte cap stay dead."""
        unlimited = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        for seed in (21, 22):
            await self._dead_letter(unlimited, image_id(seed), tmp_path / f"{seed}.jpg")
        one_entry = upload_queue_mod._directory_bytes(queue_root / "dead") // 2
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink), max_pending_bytes=one_entry)

        await queue.requeue_dead()

        assert len(queue.iter_pending()) == 1
        assert upload_queue_mod._directory_bytes(queue_root) <= one_entry
        assert len(list((queue_root / "dead").glob("*.jpg"))) == 1
        assert len(list((queue_root / "dead").glob("*.json"))) == 1

    async def test_cancel_holds_lock_until_moves_finish(
        self, queue_root: Path, sink: _FakeSink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cancelled requeue keeps the enqueue lock until its file moves are done."""
        queue = UploadQueue(queue_root, sink=cast("ImageSink", sink))
        started, release = threading.Event(), threading.Event()

        def _slow_requeue() -> None:
            started.set()
            release.wait(timeout=5)

        monkeypatch.setattr(queue, "_requeue_dead_sync", _slow_requeue)
        task = asyncio.create_task(queue.requeue_dead())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0.05)

        assert queue._enqueue_lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not queue._enqueue_lock.locked()


class TestUploadQueueWorker:
    """Tests for the runtime-owned background worker lifecycle."""

    async def test_worker_continues_after_drain_exception(self, queue_root: Path, sink: _FakeSink) -> None:
        """A drain-loop exception should be logged and retried on the next tick."""

        class _DrainSpyQueue(UploadQueue):
            def __init__(self, root: Path, *, image_sink: ImageSink) -> None:
                super().__init__(root, sink=image_sink)
                self.drain_calls = 0
                self._results: list[object] = [RuntimeError("boom"), 0]

            async def drain_once(self) -> int:
                self.drain_calls += 1
                next_result = self._results.pop(0)
                if isinstance(next_result, Exception):
                    raise next_result
                return cast("int", next_result)

        queue = _DrainSpyQueue(queue_root, image_sink=cast("ImageSink", sink))
        task = asyncio.create_task(run_upload_queue_worker(queue, poll_interval_s=0.01))
        for _ in range(20):
            if queue.drain_calls >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert queue.drain_calls >= 2
