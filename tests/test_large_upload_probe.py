from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pytest

from scripts import large_upload_probe


class FailingProbeClient:
    instance: FailingProbeClient | None = None

    def __init__(self, token: str, base_url: str) -> None:
        assert token == "test-token"
        assert base_url == "http://telegram-api:8081"
        self.closed = False
        self.probe_parent: Path | None = None
        FailingProbeClient.instance = self

    async def send_document(
        self,
        *,
        chat_id: int,
        reply_to: int,
        document: BinaryIO,
        filename: str,
        content_type: str,
        caption: str,
    ) -> None:
        assert chat_id == 123
        assert reply_to == 0
        assert filename == "telegram-transport-probe-1MiB.bin"
        assert content_type == "application/octet-stream"
        assert caption.endswith("1 MiB")
        self.probe_parent = Path(document.name).parent
        assert Path(document.name).stat().st_size == 1024 * 1024
        raise RuntimeError("simulated transport failure")

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_probe_removes_file_and_closes_client_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(large_upload_probe, "LocalBotApiClient", FailingProbeClient)
    env = {
        "BOT_TOKEN": "test-token",
        "TELEGRAM_LOCAL_API_BASE_URL": "http://telegram-api:8081",
        "OWNER_USER_ID": "123",
        "PROBE_SIZE_MIB": "1",
        "MEDIA_TMP_ROOT": str(tmp_path),
    }

    with pytest.raises(RuntimeError, match="simulated transport failure"):
        await large_upload_probe.run_probe(env)

    client = FailingProbeClient.instance
    assert client is not None
    assert client.closed
    assert client.probe_parent is not None
    assert not client.probe_parent.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_probe_rejects_oversize_before_creating_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client(token: str, base_url: str) -> None:
        del token, base_url
        raise AssertionError("client must not be created")

    monkeypatch.setattr(large_upload_probe, "LocalBotApiClient", unexpected_client)
    env = {
        "BOT_TOKEN": "test-token",
        "TELEGRAM_LOCAL_API_BASE_URL": "http://telegram-api:8081",
        "OWNER_USER_ID": "123",
        "PROBE_SIZE_MIB": "1901",
    }

    with pytest.raises(RuntimeError, match="between 1 and 1900"):
        await large_upload_probe.run_probe(env)
