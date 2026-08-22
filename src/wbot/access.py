from __future__ import annotations

from enum import Enum
from typing import Protocol


class ApprovalReader(Protocol):
    async def is_chat_approved(self, chat_id: int) -> bool: ...


class Decision(Enum):
    ALLOW = "allow"
    IGNORE = "ignore"
    BOT_MUST_NOT_BE_ADMIN = "bot_must_not_be_admin"


class AccessPolicy:
    def __init__(self, owner_user_id: int, repository: ApprovalReader) -> None:
        self.owner_user_id = owner_user_id
        self.repository = repository

    async def evaluate(
        self,
        *,
        user_id: int,
        chat_id: int,
        chat_type: str,
        bot_is_admin: bool,
    ) -> Decision:
        if chat_type == "private":
            if user_id == self.owner_user_id and chat_id == self.owner_user_id:
                return Decision.ALLOW
            return Decision.IGNORE

        if chat_type not in {"group", "supergroup"}:
            return Decision.IGNORE
        if not await self.repository.is_chat_approved(chat_id):
            return Decision.IGNORE
        if bot_is_admin:
            return Decision.BOT_MUST_NOT_BE_ADMIN
        return Decision.ALLOW

    def can_manage(self, user_id: int) -> bool:
        return user_id == self.owner_user_id
