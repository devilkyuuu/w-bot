from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from wbot.publisher import LocalBotApiClient, create_probe_file

MIB = 1024 * 1024
MAX_PROBE_MIB = 1_900


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _integer(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None


async def run_probe(env: Mapping[str, str]) -> None:
    token = _required(env, "BOT_TOKEN")
    base_url = _required(env, "TELEGRAM_LOCAL_API_BASE_URL")
    chat_id = _integer(env, "PROBE_CHAT_ID", _integer(env, "OWNER_USER_ID", 0))
    reply_to = _integer(env, "PROBE_REPLY_TO", 0)
    size_mib = _integer(env, "PROBE_SIZE_MIB", 60)
    if chat_id == 0:
        raise RuntimeError("PROBE_CHAT_ID or OWNER_USER_ID is required")
    if not 1 <= size_mib <= MAX_PROBE_MIB:
        raise RuntimeError(f"PROBE_SIZE_MIB must be between 1 and {MAX_PROBE_MIB}")

    root = Path(env.get("MEDIA_TMP_ROOT", "/tmp/wbot-media"))
    root.mkdir(parents=True, exist_ok=True)
    client = LocalBotApiClient(token=token, base_url=base_url)
    try:
        with tempfile.TemporaryDirectory(prefix="upload-probe-", dir=root) as temporary:
            probe = create_probe_file(Path(temporary) / "transport-probe.bin", size_mib * MIB)
            try:
                with probe.open("rb") as document:
                    await client.send_document(
                        chat_id=chat_id,
                        reply_to=reply_to,
                        document=document,
                        filename=f"telegram-transport-probe-{size_mib}MiB.bin",
                        content_type="application/octet-stream",
                        caption=f"Telegram Local Bot API transport probe: {size_mib} MiB",
                    )
            finally:
                probe.unlink(missing_ok=True)
    finally:
        await client.aclose()

    print(f"Upload probe succeeded ({size_mib} MiB); local probe data removed.")


def main() -> None:
    asyncio.run(run_probe(os.environ))


if __name__ == "__main__":
    main()
