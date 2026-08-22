from __future__ import annotations

import logging
import os
from typing import Any

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler

from wbot.access import AccessPolicy
from wbot.commands import BotServices, Commands
from wbot.config import Settings
from wbot.database import SQLiteRepository
from wbot.exchange import ExchangeService
from wbot.extractors.amiami import AmiAmiExtractor
from wbot.extractors.nin_nin import NinNinExtractor
from wbot.extractors.video import VideoExtractor
from wbot.extractors.x_post import XPostExtractor
from wbot.publisher import LocalBotApiClient, Publisher
from wbot.workspace import MediaGate, cleanup_stale


def build_application(settings: Settings) -> Application[Any, Any, Any, Any, Any, Any]:
    repository = SQLiteRepository(settings.database_path)
    access = AccessPolicy(settings.owner_user_id, repository)
    exchange = ExchangeService()
    video = VideoExtractor(
        max_seconds=settings.max_video_seconds,
        max_bytes=settings.max_download_bytes,
    )
    telegram_client = LocalBotApiClient(settings.bot_token, settings.local_api_base_url)
    services = BotServices(
        settings=settings,
        access=access,
        repository=repository,
        publisher=Publisher(telegram_client),
        video=video,
        amiami=AmiAmiExtractor(),
        nin_nin=NinNinExtractor(exchange),
        x_post=XPostExtractor(video),
        exchange=exchange,
        gate=MediaGate(),
    )
    commands = Commands(services)

    async def post_init(application: Application[Any, Any, Any, Any, Any, Any]) -> None:
        del application
        cleanup_stale(settings.media_tmp_root)
        await repository.initialize()

    async def post_shutdown(application: Application[Any, Any, Any, Any, Any, Any]) -> None:
        del application
        await telegram_client.aclose()

    base = settings.local_api_base_url.rstrip("/")
    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .base_url(f"{base}/bot")
        .base_file_url(f"{base}/file/bot")
        .local_mode(False)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("w", commands.w))
    application.add_handler(CommandHandler("approve", commands.approve))
    application.add_handler(CommandHandler("revoke", commands.revoke))
    application.bot_data["services"] = services
    return application


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = Settings.from_env(os.environ)
    application = build_application(settings)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
