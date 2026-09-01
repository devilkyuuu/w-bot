from __future__ import annotations

import asyncio
import html
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from wbot.domain import MediaAsset, ProductResult, SupportedUrl
from wbot.errors import RetrievalError
from wbot.extractors.common import download_asset, fetch_bytes
from wbot.workspace import JobWorkspace

AMIAMI_JAPANESE_DOMAINS = ("amiami.jp",)
MAKER_TRANSLATIONS = {
    "グッドスマイルカンパニー": "Good Smile Company",
    "スクウェア・エニックス": "Square Enix",
}


class AmiAmiExtractor:
    def __init__(self) -> None:
        self._translations: dict[str, str] = {}

    async def extract(self, url: SupportedUrl, workspace: JobWorkspace) -> ProductResult:
        code = parse_qs(urlsplit(url.normalized).query).get("gcode", [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", code):
            raise RetrievalError
        page_url = f"https://www.amiami.jp/top/detail/detail?gcode={quote(code)}"
        page, _ = await fetch_bytes(
            page_url,
            allowed_domains=AMIAMI_JAPANESE_DOMAINS,
        )
        product = _from_html(page, page_url)

        images = await _download_images(
            product[3],
            workspace.path,
            AMIAMI_JAPANESE_DOMAINS,
        )
        if not images:
            raise RetrievalError
        maker = MAKER_TRANSLATIONS.get(product[1], product[1]) if product[1] else None
        translated_name: str | None = None
        if len(product[0].encode("utf-8")) <= 500:
            try:
                async with asyncio.timeout(5):
                    translated_name = await self._translate_title(code, product[0])
            except Exception:
                pass
        return ProductResult(product[0], maker, product[2], tuple(images), translated_name)

    async def _translate_title(self, code: str, title: str) -> str:
        cached = self._translations.get(code)
        if cached is not None:
            return cached
        query = urlencode({"q": title, "langpair": "ja|en", "mt": "1"})
        payload, _ = await fetch_bytes(
            f"https://api.mymemory.translated.net/get?{query}",
            allowed_domains=("mymemory.translated.net",),
            max_bytes=1_000_000,
        )
        data = json.loads(payload)
        response = data.get("responseData", {}) if isinstance(data, dict) else {}
        translated = response.get("translatedText") if isinstance(response, dict) else None
        if not isinstance(translated, str) or not translated.strip():
            raise RetrievalError
        result = html.unescape(translated.strip())
        self._translations[code] = result
        return result


def _from_html(page: bytes, base_url: str) -> tuple[str, str | None, Decimal, list[str]]:
    raw = page.decode("utf-8", errors="replace")
    soup = BeautifulSoup(page, "html.parser")
    title_tag = soup.select_one('meta[property="og:title"]') or soup.select_one("h1")
    title_match = re.search(r"sname_simple\s*=\s*'([^']+)'", raw)
    title = html.unescape(title_match.group(1).strip()) if title_match else _tag_value(title_tag)
    text = soup.get_text("\n", strip=True)
    maker_script = re.search(r"maker_name\s*=\s*'([^']+)'", raw)
    maker_match = re.search(
        r"(?:Maker|Manufacturer)\s*[:\uFF1A]\s*([^\n]+)", text, re.I
    )
    price_match = re.search(
        r"販売価格\s*(?:[0-9]+%OFF\s*)?([0-9][0-9,]*)円",
        text,
    ) or re.search(r"(?:JPY|¥)\s*([0-9][0-9,]*)", text)
    if not title or not price_match:
        raise RetrievalError
    maker: str | None = None
    if maker_script:
        maker = html.unescape(maker_script.group(1).strip())
    elif maker_match:
        maker = maker_match.group(1).strip()
    japanese_images = re.findall(
        r"https://img\.amiami\.jp/images/product/(?:main|review)/[^\"'<>\s]+\.(?:jpe?g|png|webp)",
        raw,
        re.I,
    )
    images = japanese_images or [
        urljoin(base_url, value)
        for tag in soup.select('[data-image-large-src], meta[property="og:image"]')
        if isinstance(
            value := tag.get("data-image-large-src") or tag.get("content"),
            str,
        )
    ]
    return (
        title,
        maker,
        Decimal(price_match.group(1).replace(",", "")),
        list(dict.fromkeys(images)),
    )


def _tag_value(tag: Any) -> str | None:
    if tag is None:
        return None
    value = tag.get("content") or tag.get_text(" ", strip=True)
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _download_images(
    urls: list[str],
    root: Path,
    allowed_domains: tuple[str, ...],
) -> list[MediaAsset]:
    assets: list[MediaAsset] = []
    for index, image_url in enumerate(dict.fromkeys(urls)):
        if len(assets) == 5:
            break
        try:
            path, content_type = await download_asset(
                image_url,
                root / f"product-{index}.jpg",
                allowed_domains=allowed_domains,
                byte_limit=20 * 1024 * 1024,
            )
        except Exception:
            continue
        assets.append(MediaAsset(path=path, mime_type=content_type))
    return assets
