from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

import pytest

from wbot.database import Repository, SQLiteRepository


@dataclass
class FakeCursor:
    row: tuple[int] | None

    async def fetchone(self) -> tuple[int] | None:
        return self.row


@dataclass
class FakeConnection:
    approved: set[int]
    calls: list[tuple[str, tuple[int, ...]]]

    async def execute(self, query: str, params: tuple[int, ...] = ()) -> FakeCursor:
        compact_query = " ".join(query.split())
        self.calls.append((compact_query, params))
        if compact_query.startswith("INSERT INTO approved_chats"):
            self.approved.add(params[0])
            return FakeCursor(None)
        if compact_query.startswith("DELETE FROM approved_chats"):
            self.approved.discard(params[0])
            return FakeCursor(None)
        if compact_query.startswith("SELECT 1 FROM approved_chats"):
            return FakeCursor((1,) if params[0] in self.approved else None)
        raise AssertionError(f"Unexpected SQL operation: {compact_query}")


@dataclass
class FakeConnectionContext(AbstractAsyncContextManager[FakeConnection]):
    connection_value: FakeConnection

    async def __aenter__(self) -> FakeConnection:
        return self.connection_value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None


@dataclass
class FakePool:
    approved: set[int] = field(default_factory=set)
    calls: list[tuple[str, tuple[int, ...]]] = field(default_factory=list)

    def connection(self) -> FakeConnectionContext:
        return FakeConnectionContext(FakeConnection(self.approved, self.calls))


@pytest.mark.asyncio
async def test_approve_is_idempotent_and_persists_chat() -> None:
    pool = FakePool()
    repository = Repository(pool)

    await repository.approve_chat(chat_id=-1007, approved_by=42)
    await repository.approve_chat(chat_id=-1007, approved_by=42)

    assert await repository.is_chat_approved(-1007) is True
    assert pool.approved == {-1007}


@pytest.mark.asyncio
async def test_revoke_removes_approved_chat() -> None:
    pool = FakePool(approved={-1007})
    repository = Repository(pool)

    await repository.revoke_chat(-1007)

    assert await repository.is_chat_approved(-1007) is False


@pytest.mark.asyncio
async def test_chat_ids_are_passed_as_parameters_not_interpolated() -> None:
    pool = FakePool()
    repository = Repository(pool)

    await repository.approve_chat(chat_id=-1007, approved_by=42)

    query, params = pool.calls[0]
    assert "-1007" not in query
    assert params == (-1007, 42)


@pytest.mark.asyncio
async def test_sqlite_repository_persists_approved_chats(tmp_path: Path) -> None:
    database_path = tmp_path / "wbot.sqlite3"
    repository = SQLiteRepository(database_path)
    await repository.initialize()

    await repository.approve_chat(chat_id=-1007, approved_by=42)

    reopened = SQLiteRepository(database_path)
    await reopened.initialize()
    assert await reopened.is_chat_approved(-1007) is True

    await reopened.revoke_chat(-1007)
    assert await repository.is_chat_approved(-1007) is False
