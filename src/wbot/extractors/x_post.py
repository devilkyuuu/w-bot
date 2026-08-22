from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from wbot.domain import MediaAsset, PostResult, SupportedUrl
from wbot.errors import RetrievalError
from wbot.extractors.common import download_asset, fetch_bytes
from wbot.extractors.video import VideoExtractor
from wbot.workspace import JobWorkspace

X_PAGE_DOMAINS = ("x.com", "twitter.com")
X_MEDIA_DOMAINS = ("twimg.com",)


class XPostExtractor:
    def __init__(self, video: VideoExtractor) -> None:
        self.video = video

    async def extract(self, url: SupportedUrl, workspace: JobWorkspace) -> PostResult:
        match = re.search(r"/status/(\d+)", urlsplit(url.normalized).path)
        if not match:
            raise RetrievalError
        status_id = match.group(1)
        payload: dict[str, Any] = {}
        try:
            document, _ = await fetch_bytes(
                f"https://cdn.syndication.twimg.com/tweet-result?id={status_id}&lang=en",
                allowed_domains=X_MEDIA_DOMAINS,
            )
            decoded = json.loads(document)
            if isinstance(decoded, dict):
                payload = decoded
        except Exception:
            payload = await _html_fallback(url.normalized)

        user = payload.get("user", {})
        if not isinstance(user, dict):
            user = {}
        path_handle = urlsplit(url.normalized).path.strip("/").split("/", 1)[0]
        handle = (
            _text(user.get("screen_name"))
            or _text(payload.get("author_handle"))
            or path_handle
        )
        author = _text(user.get("name")) or _text(payload.get("author_name")) or handle
        text = _text(payload.get("text")) or _text(payload.get("description")) or ""

        if _has_video(payload):
            result = await self.video.download(url, workspace)
            return PostResult(author, handle, text, video=result.asset)

        photo_urls = _photo_urls(payload)
        photos = await _download_photos(photo_urls, workspace.path)
        if not text and not photos:
            raise RetrievalError
        return PostResult(author, handle, text, photos=tuple(photos))


async def _html_fallback(url: str) -> dict[str, Any]:
    document, _ = await fetch_bytes(url, allowed_domains=X_PAGE_DOMAINS)
    soup = BeautifulSoup(document, "html.parser")
    description = soup.select_one('meta[property="og:description"]')
    title = soup.select_one('meta[property="og:title"]')
    image_tags = soup.select('meta[property="og:image"]')
    images = [tag.get("content") for tag in image_tags if isinstance(tag.get("content"), str)]
    return {
        "description": description.get("content") if description else "",
        "author_name": title.get("content") if title else "",
        "photos": [{"url": item} for item in images],
    }


def _has_video(payload: object) -> bool:
    if isinstance(payload, dict):
        kind = payload.get("type")
        if kind in {"video", "animated_gif"}:
            return True
        return any(_has_video(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_has_video(value) for value in payload)
    return False


def _photo_urls(payload: dict[str, Any]) -> list[str]:
    roots: list[object] = []
    for key in ("photos", "mediaDetails", "media"):
        value = payload.get(key)
        if value is not None:
            roots.append(value)
    found: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            kind = value.get("type")
            for key in ("url", "media_url_https", "media_url"):
                candidate = value.get(key)
                if (
                    isinstance(candidate, str)
                    and candidate.startswith("https://")
                    and kind not in {"video", "animated_gif"}
                ):
                    found.append(candidate)
                    break
            for child in value.values():
                if isinstance(child, dict | list):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for root in roots:
        visit(root)
    return list(dict.fromkeys(found))


async def _download_photos(urls: list[str], root: Path) -> list[MediaAsset]:
    assets: list[MediaAsset] = []
    for index, url in enumerate(urls[:4]):
        try:
            path, content_type = await download_asset(
                urljoin(url, "?name=orig") if "?" not in url else url,
                root / f"x-photo-{index}.jpg",
                allowed_domains=X_MEDIA_DOMAINS,
                byte_limit=20 * 1024 * 1024,
            )
        except Exception:
            continue
        assets.append(MediaAsset(path, content_type))
    return assets


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
