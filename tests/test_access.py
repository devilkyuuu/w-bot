from dataclasses import dataclass, field

import pytest

from wbot.access import AccessPolicy, Decision


@dataclass
class ApprovedChats:
    chat_ids: set[int] = field(default_factory=set)

    async def is_chat_approved(self, chat_id: int) -> bool:
        return chat_id in self.chat_ids


@pytest.mark.asyncio
async def test_owner_private_chat_is_allowed() -> None:
    policy = AccessPolicy(owner_user_id=42, repository=ApprovedChats())

    decision = await policy.evaluate(
        user_id=42,
        chat_id=42,
        chat_type="private",
        bot_is_admin=False,
    )

    assert decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_another_users_private_chat_is_ignored() -> None:
    policy = AccessPolicy(owner_user_id=42, repository=ApprovedChats())

    decision = await policy.evaluate(
        user_id=99,
        chat_id=99,
        chat_type="private",
        bot_is_admin=False,
    )

    assert decision is Decision.IGNORE


@pytest.mark.asyncio
async def test_any_member_can_use_an_approved_group() -> None:
    policy = AccessPolicy(owner_user_id=42, repository=ApprovedChats({-1007}))

    decision = await policy.evaluate(
        user_id=99,
        chat_id=-1007,
        chat_type="supergroup",
        bot_is_admin=False,
    )

    assert decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_unapproved_group_is_silent() -> None:
    policy = AccessPolicy(owner_user_id=42, repository=ApprovedChats())

    decision = await policy.evaluate(
        user_id=99,
        chat_id=-1007,
        chat_type="supergroup",
        bot_is_admin=False,
    )

    assert decision is Decision.IGNORE


@pytest.mark.asyncio
async def test_approved_group_fails_closed_when_bot_is_admin() -> None:
    policy = AccessPolicy(owner_user_id=42, repository=ApprovedChats({-1007}))

    decision = await policy.evaluate(
        user_id=99,
        chat_id=-1007,
        chat_type="supergroup",
        bot_is_admin=True,
    )

    assert decision is Decision.BOT_MUST_NOT_BE_ADMIN


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [(42, True), (99, False)],
)
def test_only_owner_can_manage_groups(user_id: int, expected: bool) -> None:
    policy = AccessPolicy(owner_user_id=42, repository=ApprovedChats())

    assert policy.can_manage(user_id) is expected
