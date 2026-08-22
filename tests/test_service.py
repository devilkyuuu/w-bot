from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from wbot.service import run_until_stopped


class FakeUpdater:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start_polling(self, *, allowed_updates: object) -> None:
        assert allowed_updates
        self.events.append("updater.start_polling")

    async def stop(self) -> None:
        self.events.append("updater.stop")


class FakeApplication:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.events: list[str] = []
        self.updater = FakeUpdater(self.events)
        self.fail_start = fail_start
        self.post_init = self._post_init
        self.post_stop = self._post_stop
        self.post_shutdown = self._post_shutdown

    async def initialize(self) -> None:
        self.events.append("initialize")

    async def start(self) -> None:
        self.events.append("application.start")
        if self.fail_start:
            raise RuntimeError("start failed")

    async def stop(self) -> None:
        self.events.append("application.stop")

    async def shutdown(self) -> None:
        self.events.append("application.shutdown")

    async def _post_init(self, application: object) -> None:
        assert application is self
        self.events.append("post_init")

    async def _post_stop(self, application: object) -> None:
        assert application is self
        self.events.append("post_stop")

    async def _post_shutdown(self, application: object) -> None:
        assert application is self
        self.events.append("post_shutdown")


async def _wait_for_file(path: Path) -> None:
    async with asyncio.timeout(1):
        while not path.exists():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_stop_marker_runs_the_complete_polling_lifecycle(tmp_path: Path) -> None:
    application = FakeApplication()
    stop_file = tmp_path / "stop"
    ready_file = tmp_path / "ready"

    task = asyncio.create_task(
        run_until_stopped(
            cast(Any, application),
            stop_file,
            ready_file,
            poll_seconds=0.01,
        )
    )
    await _wait_for_file(ready_file)
    stop_file.touch()
    await task

    assert application.events == [
        "initialize",
        "post_init",
        "updater.start_polling",
        "application.start",
        "updater.stop",
        "application.stop",
        "post_stop",
        "application.shutdown",
        "post_shutdown",
    ]
    assert not ready_file.exists()
    assert not stop_file.exists()


@pytest.mark.asyncio
async def test_start_failure_never_claims_readiness_and_still_shuts_down(
    tmp_path: Path,
) -> None:
    application = FakeApplication(fail_start=True)
    ready_file = tmp_path / "ready"

    with pytest.raises(RuntimeError, match="start failed"):
        await run_until_stopped(
            cast(Any, application),
            tmp_path / "stop",
            ready_file,
            poll_seconds=0.01,
        )

    assert application.events == [
        "initialize",
        "post_init",
        "updater.start_polling",
        "application.start",
        "updater.stop",
        "application.shutdown",
        "post_shutdown",
    ]
    assert not ready_file.exists()


@pytest.mark.asyncio
async def test_stale_markers_are_removed_before_service_becomes_ready(tmp_path: Path) -> None:
    application = FakeApplication()
    stop_file = tmp_path / "stop"
    ready_file = tmp_path / "ready"
    stop_file.touch()
    ready_file.touch()

    task = asyncio.create_task(
        run_until_stopped(
            cast(Any, application),
            stop_file,
            ready_file,
            poll_seconds=0.01,
        )
    )
    await asyncio.sleep(0.05)

    assert not task.done()
    assert ready_file.exists()
    assert not stop_file.exists()

    stop_file.touch()
    await task
