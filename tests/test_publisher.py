from __future__ import annotations

from collections.abc import Sequence
from io import BufferedReader
from pathlib import Path
from typing import Any, BinaryIO

import httpx
import pytest

from wbot.domain import MediaAsset
from wbot.publisher import LocalBotApiClient, Publisher, PublishError, create_probe_file


class FakeTransport:
    def __init__(self, *, fail_video: bool = False) -> None:
        self.fail_video = fail_video
        self.video_call: dict[str, Any] | None = None
        self.photo_call: dict[str, Any] | None = None
        self.text_call: dict[str, Any] | None = None
        self.video_handle: BinaryIO | None = None
        self.photo_handles: tuple[BinaryIO, ...] = ()

    async def send_video(self, **kwargs: Any) -> None:
        video = kwargs["video"]
        assert isinstance(video, BufferedReader)
        assert not video.closed
        assert video.read() == b"video-bytes"
        video.seek(0)
        self.video_handle = video
        self.video_call = kwargs
        if self.fail_video:
            raise PublishError("sanitized failure")

    async def send_photos(
        self,
        *,
        photos: Sequence[tuple[str, BinaryIO, str]],
        **kwargs: Any,
    ) -> None:
        assert all(not handle.closed for _, handle, _ in photos)
        assert [handle.read() for _, handle, _ in photos] == [
            f"photo-{index}".encode() for index in range(5)
        ]
        self.photo_handles = tuple(handle for _, handle, _ in photos)
        self.photo_call = {**kwargs, "photos": photos}

    async def send_text(self, **kwargs: Any) -> None:
        self.text_call = kwargs


def _asset(path: Path, mime_type: str = "video/mp4") -> MediaAsset:
    return MediaAsset(
        path=path,
        mime_type=mime_type,
        width=1920,
        height=1080,
        duration_seconds=12.7,
    )


@pytest.mark.asyncio
async def test_video_is_uploaded_as_reply_and_handle_is_closed(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video-bytes")
    transport = FakeTransport()

    await Publisher(transport).send_video(
        chat_id=-1001,
        reply_to=42,
        asset=_asset(path),
        caption="<b>caption</b>",
    )

    assert transport.video_call is not None
    assert transport.video_call["chat_id"] == -1001
    assert transport.video_call["reply_to"] == 42
    assert transport.video_call["filename"] == "clip.mp4"
    assert transport.video_call["content_type"] == "video/mp4"
    assert transport.video_call["duration"] == 13
    assert transport.video_call["width"] == 1920
    assert transport.video_call["height"] == 1080
    assert transport.video_call["supports_streaming"] is True
    assert transport.video_call["caption_html"] == "<b>caption</b>"
    assert transport.video_handle is not None
    assert transport.video_handle.closed


@pytest.mark.asyncio
async def test_video_handle_is_closed_after_transport_error(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video-bytes")
    transport = FakeTransport(fail_video=True)

    with pytest.raises(PublishError, match="sanitized failure"):
        await Publisher(transport).send_video(-1001, 42, _asset(path), None)

    assert transport.video_handle is not None
    assert transport.video_handle.closed


@pytest.mark.asyncio
async def test_photo_album_is_capped_at_five_and_handles_close(tmp_path: Path) -> None:
    assets: list[MediaAsset] = []
    for index in range(7):
        path = tmp_path / f"photo-{index}.jpg"
        path.write_bytes(f"photo-{index}".encode())
        assets.append(MediaAsset(path=path, mime_type="image/jpeg"))
    transport = FakeTransport()

    await Publisher(transport).send_photos(
        chat_id=-1001,
        reply_to=9,
        assets=assets,
        caption_html="<b>Product</b>\nMaker",
    )

    assert transport.photo_call is not None
    assert transport.photo_call["chat_id"] == -1001
    assert transport.photo_call["reply_to"] == 9
    assert transport.photo_call["caption_html"] == "<b>Product</b>\nMaker"
    assert len(transport.photo_call["photos"]) == 5
    assert all(handle.closed for handle in transport.photo_handles)


@pytest.mark.asyncio
async def test_empty_photo_album_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one photo"):
        await Publisher(FakeTransport()).send_photos(-1001, 9, [], "caption")


@pytest.mark.asyncio
async def test_text_is_sent_as_html_reply() -> None:
    transport = FakeTransport()

    await Publisher(transport).send_text(-1001, 77, "Alice\nHello &amp; goodbye")

    assert transport.text_call == {
        "chat_id": -1001,
        "reply_to": 77,
        "text_html": "Alice\nHello &amp; goodbye",
    }


@pytest.mark.asyncio
async def test_local_client_uses_internal_base_url_and_reply_parameters() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LocalBotApiClient(
            token="123:test-token",
            base_url="http://telegram-api:8081/",
            http=http,
        )
        await client.send_text(chat_id=-1001, reply_to=33, text_html="<b>Hello</b>")

    assert client.api_origin == "http://telegram-api:8081"
    assert len(captured) == 1
    request = captured[0]
    assert request.url == "http://telegram-api:8081/bot123:test-token/sendMessage"
    body = request.content.decode()
    assert "reply_parameters=" in body
    assert "%22message_id%22%3A33" in body
    assert "parse_mode=HTML" in body


@pytest.mark.asyncio
async def test_local_client_replaces_remote_error_with_sanitized_exception() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            400,
            json={"ok": False, "description": "secret filename and upstream details"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LocalBotApiClient("123:test-token", "http://telegram-api:8081", http=http)
        with pytest.raises(PublishError, match="Telegram rejected the request") as caught:
            await client.send_text(1, 2, "hello")

    assert "secret filename" not in str(caught.value)


@pytest.mark.asyncio
async def test_local_client_streams_a_probe_document_with_multipart() -> None:
    captured_body = b""
    captured_content_type = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body, captured_content_type
        captured_content_type = request.headers["content-type"]
        captured_body = await request.aread()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LocalBotApiClient("123:test-token", "http://telegram-api:8081", http=http)
        with BufferedReader(Path(__file__).open("rb")) as document:
            await client.send_document(
                chat_id=1,
                reply_to=0,
                document=document,
                filename="probe.bin",
                content_type="application/octet-stream",
                caption="60 MiB transport probe",
            )

    assert captured_content_type.startswith("multipart/form-data; boundary=")
    assert b'name="document"; filename="probe.bin"' in captured_body
    assert b"60 MiB transport probe" in captured_body


def test_probe_file_has_requested_logical_size(tmp_path: Path) -> None:
    path = create_probe_file(tmp_path / "probe.bin", 3 * 1024 * 1024)

    assert path.stat().st_size == 3 * 1024 * 1024


def test_probe_file_rejects_non_positive_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        create_probe_file(tmp_path / "probe.bin", 0)
