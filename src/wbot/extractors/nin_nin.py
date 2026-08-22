from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from wbot.domain import ProductResult, SupportedUrl
from wbot.errors import RetrievalError
from wbot.exchange import ExchangeService
from wbot.extractors.amiami import _download_images
from wbot.extractors.common import fetch_bytes
from wbot.workspace import JobWorkspace

NIN_NIN_DOMAINS = ("nin-nin-game.com",)


class NinNinExtractor:
    def __init__(self, exchange: ExchangeService) -> None:
        self.exchange = exchange

    async def extract(self, url: SupportedUrl, workspace: JobWorkspace) -> ProductResult:
        page, _ = await fetch_bytes(url.normalized, allowed_domains=NIN_NIN_DOMAINS)
        soup = BeautifulSoup(page, "html.parser")
        product = _product_json_ld(soup)
        title = _title(soup, product)
        maker = _maker(soup, product, title)
        amount, currency = _price(soup, product)
        price_jpy = (
            amount.quantize(Decimal("1"))
            if currency == "JPY"
            else (await self.exchange.convert(amount, currency, "JPY")).quantize(Decimal("1"))
        )
        image_urls = _images(soup, product, url.normalized)
        images = await _download_images(image_urls, workspace.path, NIN_NIN_DOMAINS)
        if not images:
            raise RetrievalError
        return ProductResult(title, maker, price_jpy, tuple(images))


def _product_json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            raw = tag.string or ""
            raw = raw.replace("/* <![CDATA[ */", "").replace("/* ]]> */", "").strip()
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _walk_json(payload):
            kind = item.get("@type")
            if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
                return item
    return {}


def _walk_json(value: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_json(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_json(child))
    return found


def _title(soup: BeautifulSoup, product: dict[str, Any]) -> str:
    name = product.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    tag = soup.select_one("h1") or soup.select_one('meta[property="og:title"]')
    if tag is None:
        value: object = ""
    elif tag.name == "meta":
        value = tag.get("content")
    else:
        value = tag.get_text(" ", strip=True)
    if not isinstance(value, str) or not value.strip():
        raise RetrievalError
    return value.strip()


def _maker(soup: BeautifulSoup, product: dict[str, Any], title: str) -> str | None:
    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    if isinstance(brand, str) and brand.strip():
        return brand.strip()
    text = soup.get_text("\n", strip=True)
    match = re.search(
        r"(?:Brand/Manufacturer|Maker)\s*[:\uFF1A]\s*([^\n]+)", text, re.I
    )
    if match:
        return match.group(1).strip()
    bracket = re.search(r"\[([^\]]+)\]\s*$", title)
    return bracket.group(1).strip() if bracket else None


def _price(soup: BeautifulSoup, product: dict[str, Any]) -> tuple[Decimal, str]:
    offers = product.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict):
        value = offers.get("price") or offers.get("lowPrice")
        currency = offers.get("priceCurrency")
        if isinstance(value, int | float | str) and isinstance(currency, str):
            try:
                return Decimal(str(value).replace(",", "")), currency.upper()
            except InvalidOperation:
                pass
    text = soup.get_text(" ", strip=True)
    yen = re.search(r"¥\s*([0-9][0-9,]*)", text)
    if yen:
        return Decimal(yen.group(1).replace(",", "")), "JPY"
    raise RetrievalError


def _images(soup: BeautifulSoup, product: dict[str, Any], base_url: str) -> list[str]:
    values: list[str] = []
    for tag in soup.select(
        "#views_block img, .product-layout-gallery img, [data-image-large-src]"
    ):
        value = (
            tag.get("data-image-large-src")
            or tag.get("data-src")
            or tag.get("src")
            or tag.get("content")
        )
        if isinstance(value, str):
            values.append(value.replace("-pos_medium/", "-pos_large/"))
    image = product.get("image")
    if isinstance(image, str):
        values.append(image)
    elif isinstance(image, list):
        values.extend(item for item in image if isinstance(item, str))
    if not values:
        for tag in soup.select('meta[property="og:image"]'):
            value = tag.get("content")
            if isinstance(value, str):
                values.append(value)

    found: list[str] = []
    seen_ids: set[str] = set()
    for value in values:
        absolute = urljoin(base_url, value)
        match = re.search(r"/(\d+)-(?:pos_|large_default)", absolute)
        identity = match.group(1) if match else absolute
        if identity not in seen_ids:
            seen_ids.add(identity)
            found.append(absolute)
    return found
