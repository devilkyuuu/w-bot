from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from wbot.access import AccessPolicy, Decision
from wbot.commands import BotServices, Commands


@dataclass
class RecordingMessage:
    text: str
    message_id: int = 17
    replies: list[str] = field(default_factory=list)

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


@dataclass
class CountingAccess:
    calls: int = 0

    async def evaluate(self, **kwargs: Any) -> Decision:
        del kwargs
        self.calls += 1
        return Decision.ALLOW


@dataclass
class ToggleRepository:
    approved: bool = True
    changes: list[tuple[int, str, bool]] = field(default_factory=list)

    async def is_chat_approved(self, chat_id: int) -> bool:
        del chat_id
        return self.approved

    async def set_media_category_enabled(
        self, chat_id: int, category: str, *, enabled: bool
    ) -> None:
        self.changes.append((chat_id, category, enabled))


@dataclass
class FilteringRepository(ToggleRepository):
    enabled: dict[str, bool] = field(
        default_factory=lambda: {"social": True, "figures": True}
    )
    checks: list[tuple[int, str]] = field(default_factory=list)

    async def is_media_category_enabled(self, chat_id: int, category: str) -> bool:
        self.checks.append((chat_id, category))
        return self.enabled[category]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "ordinary group conversation",
        "/w https://x.com/alice/status/123",
        "https://example.com/not-supported",
        "https://x.com/home",
        "https://www.amiami.com/eng/detail",
        "https://www.nin-nin-game.com/en/",
        "https://x.com/a/status/1 https://x.com/b/status/2",
    ],
)
async def test_non_media_messages_are_silent_before_access_checks(text: str) -> None:
    access = CountingAccess()
    message = RecordingMessage(text)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=99),
        effective_chat=SimpleNamespace(id=-1007, type="supergroup"),
    )
    context = SimpleNamespace(bot=SimpleNamespace())
    services = cast(BotServices, SimpleNamespace(access=access))

    await Commands(services).media(cast(Any, update), cast(Any, context))

    assert access.calls == 0
    assert message.replies == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "category", "enabled", "reply"),
    [
        ("social_off", "social", False, "Social media disabled."),
        ("social_on", "social", True, "Social media enabled."),
        ("figures_off", "figures", False, "Figure websites disabled."),
        ("figures_on", "figures", True, "Figure websites enabled."),
    ],
)
async def test_owner_can_change_category_for_current_approved_group(
    method_name: str,
    category: str,
    enabled: bool,
    reply: str,
) -> None:
    repository = ToggleRepository()
    access = AccessPolicy(42, repository)
    message = RecordingMessage(f"/{method_name}")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=-1007, type="supergroup"),
    )
    services = cast(
        BotServices,
        SimpleNamespace(access=access, repository=repository),
    )

    command = getattr(Commands(services), method_name)
    await command(cast(Any, update), cast(Any, SimpleNamespace()))

    assert repository.changes == [(-1007, category, enabled)]
    assert message.replies == [reply]


@pytest.mark.asyncio
async def test_non_owner_cannot_change_category() -> None:
    repository = ToggleRepository()
    access = AccessPolicy(42, repository)
    message = RecordingMessage("/social_off")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=99),
        effective_chat=SimpleNamespace(id=-1007, type="group"),
    )
    services = cast(
        BotServices,
        SimpleNamespace(access=access, repository=repository),
    )

    await Commands(services).social_off(cast(Any, update), cast(Any, SimpleNamespace()))

    assert repository.changes == []
    assert message.replies == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("link", "disabled_category"),
    [
        ("https://www.tiktok.com/@alice/video/123", "social"),
        ("https://www.facebook.com/watch/?v=123", "social"),
        ("https://x.com/alice/status/123", "social"),
        ("https://www.amiami.com/eng/detail?gcode=FIGURE-207185", "figures"),
        (
            "https://www.nin-nin-game.com/en/nendoroid/254320-product.html",
            "figures",
        ),
    ],
)
async def test_disabled_category_links_are_silent_before_admin_or_media_work(
    link: str,
    disabled_category: str,
) -> None:
    repository = FilteringRepository()
    repository.enabled[disabled_category] = False
    access = AccessPolicy(42, repository)
    message = RecordingMessage(link)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=99),
        effective_chat=SimpleNamespace(id=-1007, type="supergroup"),
    )

    class RecordingBot:
        id = 500
        admin_checks = 0

        async def get_chat_member(self, *args: Any) -> Any:
            del args
            self.admin_checks += 1
            return SimpleNamespace(status="member")

    bot = RecordingBot()
    context = SimpleNamespace(bot=bot)
    services = cast(
        BotServices,
        SimpleNamespace(access=access, repository=repository),
    )

    await Commands(services).media(cast(Any, update), cast(Any, context))

    assert repository.checks == [(-1007, disabled_category)]
    assert bot.admin_checks == 0
    assert message.replies == []


@pytest.mark.asyncio
async def test_product_caption_shows_japanese_and_translated_titles_without_maker_label() -> None:
    class FixedExchange:
        async def jpy_to_eur(self, price_jpy: Decimal) -> Decimal:
            assert price_jpy == Decimal("28710")
            return Decimal("165.20")

    class RecordingPublisher:
        caption: str | None = None

        async def send_photos(self, *args: Any) -> None:
            self.caption = cast(str, args[3])

    publisher = RecordingPublisher()
    services = cast(
        BotServices,
        SimpleNamespace(exchange=FixedExchange(), publisher=publisher),
    )
    product = SimpleNamespace(
        name="ファイナルファンタジーVIIリバース PLAY ARTS真 セフィロス",
        translated_name="Final Fantasy VII Rebirth PLAY ARTS <True> Sephiroth",
        manufacturer="Square & Enix",
        price_jpy=Decimal("28710"),
        images=(object(),),
    )

    await Commands(services)._publish_product(cast(Any, product), -1007, 17)

    assert publisher.caption == (
        "<b>ファイナルファンタジーVIIリバース PLAY ARTS真 セフィロス</b>\n"
        "<i>Final Fantasy VII Rebirth PLAY ARTS &lt;True&gt; Sephiroth</i>\n"
        "¥28,710\n"
        "≈ €165.20\n"
        "Square &amp; Enix"
    )


@pytest.mark.asyncio
async def test_oversized_translation_is_omitted_without_losing_product_album() -> None:
    class FixedExchange:
        async def jpy_to_eur(self, price_jpy: Decimal) -> Decimal:
            del price_jpy
            return Decimal("10.00")

    class RecordingPublisher:
        caption: str | None = None
        calls = 0

        async def send_photos(self, *args: Any) -> None:
            self.calls += 1
            self.caption = cast(str, args[3])

    publisher = RecordingPublisher()
    services = cast(
        BotServices,
        SimpleNamespace(exchange=FixedExchange(), publisher=publisher),
    )
    product = SimpleNamespace(
        name="日本語の商品名",
        translated_name="T" * 2_000,
        manufacturer="Square Enix",
        price_jpy=Decimal("1000"),
        images=(object(),),
    )

    await Commands(services)._publish_product(cast(Any, product), -1007, 17)

    assert publisher.calls == 1
    assert publisher.caption == (
        "<b>日本語の商品名</b>\n"
        "¥1,000\n"
        "≈ €10.00\n"
        "Square Enix"
    )
    assert len(publisher.caption) <= 1_024
