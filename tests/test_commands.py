from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from wbot.access import Decision
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
