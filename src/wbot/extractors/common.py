from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from wbot.errors import MediaTooLargeError, RetrievalError

USER_AGENT = "WMediaBot/1.0 (private Telegram link preview bot)"
MAX_PAGE_BYTES = 5 * 1024 * 1024


def validate_remote_url(url: str, allowed_domains: Iterable[str]) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    allowed = tuple(domain.lower() for domain in allowed_domains)
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not any(host == domain or host.endswith(f".{domain}") for domain in allowed)
    ):
        raise RetrievalError
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return url
    raise RetrievalError


async def fetch_bytes(
    url: str,
    *,
    allowed_domains: Iterable[str],
    max_bytes: int = MAX_PAGE_BYTES,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    current = validate_remote_url(url, allowed_domains)
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, headers=request_headers
    ) as client:
        for _ in range(5):
            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise RetrievalError
                        current = validate_remote_url(
                            urljoin(current, location), allowed_domains
                        )
                        continue
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise MediaTooLargeError
                    return bytes(content), response.headers.get(
                        "content-type", "application/octet-stream"
                    ).split(";", 1)[0]
            except (httpx.HTTPError, OSError):
                raise RetrievalError from None
    raise RetrievalError


async def download_asset(
    url: str,
    destination: Path,
    *,
    allowed_domains: Iterable[str],
    byte_limit: int,
) -> tuple[Path, str]:
    data, content_type = await fetch_bytes(
        url,
        allowed_domains=allowed_domains,
        max_bytes=byte_limit,
    )
    destination.write_bytes(data)
    return destination, content_type
