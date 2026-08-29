from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.utils import DownloadError  # type: ignore[import-untyped]

from wbot.domain import MediaAsset, SupportedUrl, VideoResult
from wbot.errors import MediaTooLargeError, RetrievalError, VideoTooLongError
from wbot.workspace import JobWorkspace, WorkspaceLimitError


class _QuietLogger:
    def debug(self, message: str) -> None:
        del message

    def warning(self, message: str) -> None:
        del message

    def error(self, message: str) -> None:
        del message


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    duration_seconds: float | None
    estimated_bytes: int | None
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class VideoStream:
    codec: str
    width: int
    height: int


class VideoExtractor:
    def __init__(self, *, max_seconds: int, max_bytes: int) -> None:
        self.max_seconds = max_seconds
        self.max_bytes = max_bytes

    async def inspect(self, url: SupportedUrl) -> VideoMetadata:
        info = await asyncio.to_thread(self._extract_info, url.normalized, False, None)
        metadata = _metadata(info)
        self._validate_metadata(metadata)
        return metadata

    async def download(
        self,
        url: SupportedUrl,
        workspace: JobWorkspace,
    ) -> VideoResult:
        info = await asyncio.to_thread(self._extract_info, url.normalized, False, None)
        metadata = _metadata(info)
        self._validate_metadata(metadata)
        try:
            workspace.reserve(metadata.estimated_bytes)
        except WorkspaceLimitError:
            raise MediaTooLargeError from None

        await asyncio.to_thread(self._extract_info, url.normalized, True, workspace.path)
        candidates = sorted(workspace.path.glob("media*.mp4"), key=lambda item: item.stat().st_size)
        if not candidates:
            raise RetrievalError
        path = candidates[-1]
        if path.stat().st_size > self.max_bytes:
            raise MediaTooLargeError
        path, stream = await asyncio.to_thread(self._ensure_compatible, path)
        if path.stat().st_size > self.max_bytes:
            raise MediaTooLargeError
        return VideoResult(
            asset=MediaAsset(
                path=path,
                mime_type="video/mp4",
                width=stream.width,
                height=stream.height,
                duration_seconds=metadata.duration_seconds,
            )
        )

    def _ensure_compatible(self, path: Path) -> tuple[Path, VideoStream]:
        stream = _probe(path)
        oversized = max(stream.width, stream.height) > 1920 or min(
            stream.width, stream.height
        ) > 1080
        if stream.codec == "h264" and not oversized:
            return path, stream

        output = path.with_name("compatible.mp4")
        command = ["ffmpeg", "-y", "-i", str(path)]
        if oversized:
            width, height = ((1920, 1080) if stream.width >= stream.height else (1080, 1920))
            command.extend(
                [
                    "-vf",
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
                ]
            )
        command.extend(
            [
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        try:
            subprocess.run(
                command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except (OSError, subprocess.SubprocessError):
            raise RetrievalError from None
        path.unlink()
        return output, _probe(output)

    def _validate_metadata(self, metadata: VideoMetadata) -> None:
        if metadata.duration_seconds is not None and metadata.duration_seconds > self.max_seconds:
            raise VideoTooLongError
        if metadata.estimated_bytes is not None and metadata.estimated_bytes > self.max_bytes:
            raise MediaTooLargeError

    def _extract_info(
        self,
        url: str,
        download: bool,
        output_directory: Path | None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "logger": _QuietLogger(),
            "noplaylist": True,
            "playlist_items": "1",
            "socket_timeout": 20,
            "retries": 2,
            "fragment_retries": 2,
            "max_filesize": self.max_bytes,
            "format": (
                "bestvideo[height<=1920][width<=1920][ext=mp4][vcodec^=avc1]+"
                "bestaudio[ext=m4a]/bestvideo[height<=1920][width<=1920][ext=mp4]+"
                "bestaudio[ext=m4a]/best[height<=1920][width<=1920][ext=mp4]/"
                "best[ext=mp4]"
            ),
            "merge_output_format": "mp4",
        }
        if output_directory is not None:
            options["outtmpl"] = str(output_directory / "media.%(ext)s")
        try:
            with YoutubeDL(options) as downloader:
                result = downloader.extract_info(url, download=download)
        except (DownloadError, OSError):
            raise RetrievalError from None
        if not isinstance(result, dict):
            raise RetrievalError
        return result


def _metadata(info: dict[str, Any]) -> VideoMetadata:
    duration = _number(info.get("duration"))
    width = _integer(info.get("width"))
    height = _integer(info.get("height"))
    size = _integer(info.get("filesize")) or _integer(info.get("filesize_approx"))
    return VideoMetadata(duration, size, width, height)


def _probe(path: Path) -> VideoStream:
    try:
        result = subprocess.run(
            (
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
                str(path),
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        stream = json.loads(result.stdout)["streams"][0]
        codec = stream["codec_name"]
        width = stream["width"]
        height = stream["height"]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, IndexError):
        raise RetrievalError from None
    if not isinstance(codec, str) or not isinstance(width, int) or not isinstance(height, int):
        raise RetrievalError
    return VideoStream(codec, width, height)


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _integer(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
