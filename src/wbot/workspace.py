from __future__ import annotations

import asyncio
import os
import shutil
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Generic, TypeVar
from uuid import uuid4

T = TypeVar("T")


class WorkspaceLimitError(ValueError):
    """Raised when a job would exceed its temporary-storage allowance."""


class JobWorkspace:
    def __init__(self, root: Path, byte_limit: int) -> None:
        if byte_limit <= 0:
            raise ValueError("byte_limit must be positive")
        self.root = root
        self.byte_limit = byte_limit
        self.path = root / uuid4().hex
        self._entered = False

    @classmethod
    def create(cls, root: Path, byte_limit: int) -> JobWorkspace:
        return cls(root, byte_limit)

    async def __aenter__(self) -> JobWorkspace:
        if self._entered:
            raise RuntimeError("workspace cannot be entered twice")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.mkdir(parents=False, exist_ok=False)
        self._entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self.cleanup()

    def reserve(self, expected_bytes: int | None) -> None:
        if expected_bytes is None:
            return
        if expected_bytes < 0:
            raise ValueError("expected_bytes must not be negative")
        if expected_bytes > self.byte_limit:
            raise WorkspaceLimitError("predicted download exceeds the temporary-storage limit")

    def assert_within_limit(self) -> None:
        if _tree_size(self.path) > self.byte_limit:
            raise WorkspaceLimitError("download exceeds the temporary-storage limit")

    def cleanup(self) -> None:
        _remove_path(self.path)


def cleanup_stale(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        _remove_path(child)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _tree_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    pending = deque([root])
    while pending:
        directory = pending.popleft()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
    return total


class MediaGate(Generic[T]):
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(1)

    async def run(self, job: Callable[[], Awaitable[T]]) -> T:
        async with self._semaphore:
            return await job()
