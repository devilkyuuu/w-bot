from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import BinaryIO, Protocol

import httpx

from wbot.domain import MediaAsset


class PublishError(RuntimeError):
    """A sanitized Telegram publishing failure safe for internal handling."""


class BotApiTransport(Protocol):
    async def send_video(
        self,
        *,
        chat_id: int,
        reply_to: int,
        video: BinaryIO,
        filename: str,
        content_type: str,
        duration: int | None,
        width: int | None,
        height: int | None,
        supports_streaming: bool,
        caption_html: str | None,
    ) -> None: ...

    async def send_photos(
        self,
        *,
        chat_id: int,
        reply_to: int,
        photos: Sequence[tuple[str, BinaryIO, str]],
        caption_html: str,
    ) -> None: ...

    async def send_text(
        self,
        *,
        chat_id: int,
        reply_to: int,
        text_html: str,
    ) -> None: ...


class Publisher:
    """Publishes normalized results while guaranteeing local file handles close."""

    def __init__(self, transport: BotApiTransport, *, max_album_photos: int = 5) -> None:
        if max_album_photos <= 0:
            raise ValueError("max_album_photos must be positive")
        self._transport = transport
        self._max_album_photos = max_album_photos

    async def send_video(
        self,
        chat_id: int,
        reply_to: int,
        asset: MediaAsset,
        caption: str | None,
    ) -> None:
        duration = round(asset.duration_seconds) if asset.duration_seconds is not None else None
        with asset.path.open("rb") as video:
            await self._transport.send_video(
                chat_id=chat_id,
                reply_to=reply_to,
                video=video,
                filename=asset.path.name,
                content_type=asset.mime_type,
                duration=duration,
                width=asset.width,
                height=asset.height,
                supports_streaming=True,
                caption_html=caption,
            )

    async def send_photos(
        self,
        chat_id: int,
        reply_to: int,
        assets: Sequence[MediaAsset],
        caption_html: str,
    ) -> None:
        selected = tuple(assets[: self._max_album_photos])
        if not selected:
            raise ValueError("at least one photo is required")

        with ExitStack() as stack:
            photos = tuple(
                (
                    asset.path.name,
                    stack.enter_context(asset.path.open("rb")),
                    asset.mime_type,
                )
                for asset in selected
            )
            await self._transport.send_photos(
                chat_id=chat_id,
                reply_to=reply_to,
                photos=photos,
                caption_html=caption_html,
            )

    async def send_text(self, chat_id: int, reply_to: int, text_html: str) -> None:
        await self._transport.send_text(
            chat_id=chat_id,
            reply_to=reply_to,
            text_html=text_html,
        )


class LocalBotApiClient:
    """Small streaming client for a private Telegram Local Bot API server."""

    def __init__(
        self,
        token: str,
        base_url: str,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("token must not be empty")
        self.api_origin = base_url.rstrip("/")
        self._endpoint_root = f"{self.api_origin}/bot{token}"
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=900, write=900, pool=10),
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def send_video(
        self,
        *,
        chat_id: int,
        reply_to: int,
        video: BinaryIO,
        filename: str,
        content_type: str,
        duration: int | None,
        width: int | None,
        height: int | None,
        supports_streaming: bool,
        caption_html: str | None,
    ) -> None:
        data = self._common_data(chat_id, reply_to)
        data.update(
            _present_strings(
                duration=duration,
                width=width,
                height=height,
                supports_streaming=supports_streaming,
                caption=caption_html,
                parse_mode="HTML" if caption_html is not None else None,
            )
        )
        await self._post(
            "sendVideo",
            data=data,
            files={"video": (filename, video, content_type)},
        )

    async def send_photos(
        self,
        *,
        chat_id: int,
        reply_to: int,
        photos: Sequence[tuple[str, BinaryIO, str]],
        caption_html: str,
    ) -> None:
        media: list[dict[str, str]] = []
        files: dict[str, tuple[str, BinaryIO, str]] = {}
        for index, (filename, handle, content_type) in enumerate(photos):
            field_name = f"photo{index}"
            item = {"type": "photo", "media": f"attach://{field_name}"}
            if index == 0:
                item.update({"caption": caption_html, "parse_mode": "HTML"})
            media.append(item)
            files[field_name] = (filename, handle, content_type)

        data = self._common_data(chat_id, reply_to)
        data["media"] = json.dumps(media, ensure_ascii=False, separators=(",", ":"))
        await self._post("sendMediaGroup", data=data, files=files)

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
        data = self._common_data(chat_id, reply_to)
        data["caption"] = caption
        await self._post(
            "sendDocument",
            data=data,
            files={"document": (filename, document, content_type)},
        )

    async def send_text(self, chat_id: int, reply_to: int, text_html: str) -> None:
        data = self._common_data(chat_id, reply_to)
        data.update({"text": text_html, "parse_mode": "HTML"})
        await self._post("sendMessage", data=data)

    @staticmethod
    def _common_data(chat_id: int, reply_to: int) -> dict[str, str]:
        data = {"chat_id": str(chat_id)}
        if reply_to > 0:
            data["reply_parameters"] = json.dumps(
                {
                    "message_id": reply_to,
                    "allow_sending_without_reply": True,
                },
                separators=(",", ":"),
            )
        return data

    async def _post(
        self,
        method: str,
        *,
        data: Mapping[str, str],
        files: Mapping[str, tuple[str, BinaryIO, str]] | None = None,
    ) -> None:
        try:
            response = await self._http.post(
                f"{self._endpoint_root}/{method}",
                data=data,
                files=files,
            )
        except httpx.HTTPError:
            raise PublishError("Telegram request failed") from None

        try:
            payload = response.json()
        except ValueError:
            raise PublishError("Telegram returned an invalid response") from None
        if response.is_error or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise PublishError("Telegram rejected the request") from None


def _present_strings(**values: int | bool | str | None) -> dict[str, str]:
    return {
        name: str(value).lower() if isinstance(value, bool) else str(value)
        for name, value in values.items()
        if value is not None
    }


def create_probe_file(path: Path, size_bytes: int) -> Path:
    """Create a synthetic file without holding its whole contents in memory."""
    if size_bytes <= 0:
        raise ValueError("size_bytes must be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as probe:
        probe.truncate(size_bytes)
    return path
