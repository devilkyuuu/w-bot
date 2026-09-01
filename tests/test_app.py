from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from telegram.ext import CommandHandler, MessageHandler

from wbot.app import build_application
from wbot.config import Settings
from wbot.publisher import LocalBotApiClient, Publisher


@pytest.mark.asyncio
async def test_application_routes_text_messages_without_registering_w_command(
    tmp_path: Path,
) -> None:
    settings = Settings(
        bot_token="123456:test-token",
        telegram_api_id=12345,
        telegram_api_hash="test-hash",
        owner_user_id=42,
        database_path=tmp_path / "wbot.sqlite3",
        local_api_base_url="http://127.0.0.1:8081",
        media_tmp_root=tmp_path / "media",
        max_download_bytes=1_000_000,
        max_video_seconds=300,
    )
    application = build_application(settings)

    try:
        handlers = [handler for group in application.handlers.values() for handler in group]
        assert any(
            isinstance(handler, MessageHandler)
            and getattr(handler.callback, "__name__", "") == "media"
            for handler in handlers
        )
        assert not any(
            isinstance(handler, CommandHandler) and "w" in handler.commands
            for handler in handlers
        )
    finally:
        services = application.bot_data["services"]
        publisher = cast(Publisher, services.publisher)
        client = cast(LocalBotApiClient, publisher._transport)
        await client.aclose()
