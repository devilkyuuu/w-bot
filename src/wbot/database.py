from __future__ import annotations

from types import TracebackType
from typing import Protocol


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
