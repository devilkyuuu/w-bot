from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import Application

from wbot.config import Settings


async def run_until_stopped(
    application: Application[Any, Any, Any, Any, Any, Any],
    stop_file: Path,
    ready_file: Path,
    poll_seconds: float = 0.25,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")

    stop_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    initialized = False
    polling = False
    started = False
    try:
        await application.initialize()
        initialized = True
        if application.post_init is not None:
            await application.post_init(application)

        updater = application.updater
        if updater is None:
            raise RuntimeError("polling updater is unavailable")
        await updater.start_polling(allowed_updates=Update.ALL_TYPES)
        polling = True

        await application.start()
        started = True
        ready_file.touch(exist_ok=False)
        while not stop_file.exists():
            await asyncio.sleep(poll_seconds)
    finally:
        ready_file.unlink(missing_ok=True)
        stop_file.unlink(missing_ok=True)
        updater = application.updater
        if polling and updater is not None:
            await updater.stop()
        if started:
            await application.stop()
            if application.post_stop is not None:
                await application.post_stop(application)
        if initialized:
            await application.shutdown()
            if application.post_shutdown is not None:
                await application.post_shutdown(application)


def run_service(settings: Settings, stop_file: Path, ready_file: Path) -> None:
    from wbot.app import build_application

    asyncio.run(run_until_stopped(build_application(settings), stop_file, ready_file))
