import asyncio
from pathlib import Path

import pytest

from wbot.workspace import JobWorkspace, MediaGate, WorkspaceLimitError, cleanup_stale


@pytest.mark.asyncio
async def test_successful_job_removes_its_directory(tmp_path: Path) -> None:
    async with JobWorkspace.create(tmp_path, byte_limit=1_000_000) as job:
        (job.path / "video.mp4").write_bytes(b"video")
        assert job.path.exists()

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_exception_still_removes_workspace(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="download failed"):
        async with JobWorkspace.create(tmp_path, byte_limit=1_000_000) as job:
            (job.path / "partial.mp4").write_bytes(b"partial")
            raise RuntimeError("download failed")

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_cancellation_still_removes_workspace(tmp_path: Path) -> None:
    with pytest.raises(asyncio.CancelledError):
        async with JobWorkspace.create(tmp_path, byte_limit=1_000_000) as job:
            (job.path / "partial.mp4").write_bytes(b"partial")
            raise asyncio.CancelledError

    assert list(tmp_path.iterdir()) == []


def test_startup_cleanup_removes_stale_children_but_keeps_root(tmp_path: Path) -> None:
    stale_directory = tmp_path / "old-job"
    stale_directory.mkdir()
    (stale_directory / "partial.mp4").write_bytes(b"partial")
    (tmp_path / "orphan.part").write_bytes(b"partial")

    cleanup_stale(tmp_path)

    assert tmp_path.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_predicted_oversize_file_is_rejected_before_download(tmp_path: Path) -> None:
    async with JobWorkspace.create(tmp_path, byte_limit=10) as job:
        with pytest.raises(WorkspaceLimitError):
            job.reserve(11)


@pytest.mark.asyncio
async def test_actual_file_growth_above_limit_is_rejected(tmp_path: Path) -> None:
    async with JobWorkspace.create(tmp_path, byte_limit=10) as job:
        (job.path / "download.part").write_bytes(b"12345678901")

        with pytest.raises(WorkspaceLimitError):
            job.assert_within_limit()


@pytest.mark.asyncio
async def test_media_gate_runs_only_one_job_at_a_time() -> None:
    gate: MediaGate[str] = MediaGate()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    async def first_job() -> str:
        first_started.set()
        await release_first.wait()
        return "first"

    async def second_job() -> str:
        second_started.set()
        return "second"

    first_task = asyncio.create_task(gate.run(first_job))
    second_task: asyncio.Task[str] | None = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=0.5)
        second_task = asyncio.create_task(gate.run(second_job))
        await asyncio.sleep(0)

        assert second_started.is_set() is False

        release_first.set()
        results = await asyncio.gather(first_task, second_task)
        assert tuple(results) == ("first", "second")
        assert second_started.is_set() is True
    finally:
        for task in (first_task, second_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (first_task, second_task) if task is not None),
            return_exceptions=True,
        )
