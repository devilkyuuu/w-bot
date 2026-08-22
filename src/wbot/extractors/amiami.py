from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from wbot.domain import MediaAsset, ProductResult, SupportedUrl
from wbot.errors import RetrievalError
from wbot.extractors.common import download_asset, fetch_bytes
from wbot.workspace import JobWorkspace

AMIAMI_DOMAINS = ("amiami.com",)


class AmiAmiExtractor:
    async def extract(self, url: SupportedUrl, workspace: JobWorkspace) -> ProductResult:
        code = parse_qs(urlsplit(url.normalized).query).get("gcode", [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", code):
            raise RetrievalError
        api_url = f"https://api.amiami.com/api/v1.0/item?gcode={quote(code)}&lang=eng"
        try:
            payload, _ = await fetch_bytes(
                api_url,
                allowed_domains=AMIAMI_DOMAINS,
                headers={"x-user-key": "amiami_dev"},
            )
            data = json.loads(payload)
            item = data.get("item", data) if isinstance(data, dict) else {}
            product = _from_api(item)
            embedded = data.get("_embedded", {}) if isinstance(data, dict) else {}
            product = (
                product[0],
                product[1],
                product[2],
                list(dict.fromkeys([*product[3], *_collect_image_urls(embedded)])),
            )
        except Exception:
            page, _ = await fetch_bytes(url.normalized, allowed_domains=AMIAMI_DOMAINS)
            product = _from_html(page, url.normalized)

        images = await _download_images(product[3], workspace.path, AMIAMI_DOMAINS)
        if not images:
            raise RetrievalError
        return ProductResult(product[0], product[1], product[2], tuple(images))


def _from_api(item: object) -> tuple[str, str | None, Decimal, list[str]]:
    if not isinstance(item, dict):
        raise RetrievalError
    title = _string(item, "gname", "sname", "name")
    maker = _string(item, "maker_name", "maker", "manufacturer", required=False)
    price = _decimal(item, "min_price", "price", "list_price")
    image_urls = _collect_image_urls(item)
    if not title or price is None:
        raise RetrievalError
    return title, maker, price, image_urls


def _from_html(page: bytes, base_url: str) -> tuple[str, str | None, Decimal, list[str]]:
    soup = BeautifulSoup(page, "html.parser")
    title_tag = soup.select_one('meta[property="og:title"]') or soup.select_one("h1")
    title = _tag_value(title_tag)
    text = soup.get_text("\n", strip=True)
    maker_match = re.search(r"(?:Maker|Manufacturer)\s*[:\uFF1A]\s*([^\n]+)", text, re.I)
    price_match = re.search(r"(?:JPY|¥)\s*([0-9][0-9,]*)", text)
    if not title or not price_match:
        raise RetrievalError
    images = [
        urljoin(base_url, value)
        for tag in soup.select('[data-image-large-src], meta[property="og:image"]')
        if isinstance(
            value := tag.get("data-image-large-src") or tag.get("content"),
            str,
        )
    ]
    return (
        title,
        maker_match.group(1).strip() if maker_match else None,
        Decimal(price_match.group(1).replace(",", "")),
        images,
    )


def _string(
    item: dict[str, Any],
    *keys: str,
    required: bool = True,
) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if required:
        raise RetrievalError
    return None


def _decimal(item: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, int | float | str) and not isinstance(value, bool):
            try:
                return Decimal(str(value).replace(",", "")).quantize(Decimal("1"))
            except InvalidOperation:
                continue
    return None


def _collect_image_urls(value: object) -> list[str]:
    found: list[str] = []

    def visit(current: object, key: str = "") -> None:
        if isinstance(current, dict):
            for child_key, child in current.items():
                visit(child, str(child_key).lower())
        elif isinstance(current, list):
            for child in current:
                visit(child, key)
        elif isinstance(current, str) and (
            "image" in key or re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", current, re.I)
        ):
            if current.startswith("//"):
                current = f"https:{current}"
            elif current.startswith("/"):
                current = urljoin("https://img.amiami.com", current)
            if current.startswith("https://") and current not in found:
                found.append(current)

    visit(value)
    return found


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
