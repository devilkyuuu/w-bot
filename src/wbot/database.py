from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Protocol


class ApprovalRepository(Protocol):
    async def approve_chat(self, chat_id: int, approved_by: int) -> None: ...

    async def revoke_chat(self, chat_id: int) -> None: ...

    async def is_chat_approved(self, chat_id: int) -> bool: ...


class Cursor(Protocol):
    async def fetchone(self) -> tuple[int] | None: ...


class Connection(Protocol):
    async def execute(self, query: str, params: tuple[int, ...] = ()) -> Cursor: ...


class ConnectionContext(Protocol):
    async def __aenter__(self) -> Connection: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class ConnectionPool(Protocol):
    def connection(self) -> ConnectionContext: ...


class Repository:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    async def initialize(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approved_chats (
                    chat_id BIGINT PRIMARY KEY,
                    approved_by BIGINT NOT NULL,
                    approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS exchange_rates (
                    currency TEXT PRIMARY KEY,
                    units_per_eur NUMERIC NOT NULL,
                    observed_at DATE NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    async def approve_chat(self, chat_id: int, approved_by: int) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO approved_chats (chat_id, approved_by)
                VALUES (%s, %s)
                ON CONFLICT (chat_id) DO UPDATE
                SET approved_by = EXCLUDED.approved_by, approved_at = NOW()
                """,
                (chat_id, approved_by),
            )

    async def revoke_chat(self, chat_id: int) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                "DELETE FROM approved_chats WHERE chat_id = %s",
                (chat_id,),
            )

    async def is_chat_approved(self, chat_id: int) -> bool:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM approved_chats WHERE chat_id = %s",
                (chat_id,),
            )
            return await cursor.fetchone() is not None


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize)

    async def approve_chat(self, chat_id: int, approved_by: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._approve_chat, chat_id, approved_by)

    async def revoke_chat(self, chat_id: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._revoke_chat, chat_id)

    async def is_chat_approved(self, chat_id: int) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self._is_chat_approved, chat_id)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approved_chats (
                    chat_id INTEGER PRIMARY KEY,
                    approved_by INTEGER NOT NULL,
                    approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _approve_chat(self, chat_id: int, approved_by: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO approved_chats (chat_id, approved_by)
                VALUES (?, ?)
                ON CONFLICT (chat_id) DO UPDATE SET
                    approved_by = excluded.approved_by,
                    approved_at = CURRENT_TIMESTAMP
                """,
                (chat_id, approved_by),
            )

    def _revoke_chat(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM approved_chats WHERE chat_id = ?", (chat_id,))

    def _is_chat_approved(self, chat_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM approved_chats WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return row is not None
