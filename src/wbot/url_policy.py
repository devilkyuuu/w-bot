from __future__ import annotations

import ipaddress
import re
from urllib.parse import SplitResult, urlsplit, urlunsplit

from wbot.domain import SourceKind, SupportedUrl


class RequestSyntaxError(ValueError):
    """Raised when `/w` does not contain exactly one URL."""


class UnsupportedUrlError(ValueError):
    """Raised when a URL is unsupported or unsafe."""


_COMMAND_RE = re.compile(r"^/w(?:@[A-Za-z0-9_]+)?\s+(\S+)\s*$", re.IGNORECASE)

_HOST_TO_SOURCE: dict[str, SourceKind] = {
    "tiktok.com": SourceKind.TIKTOK,
    "www.tiktok.com": SourceKind.TIKTOK,
    "m.tiktok.com": SourceKind.TIKTOK,
    "vm.tiktok.com": SourceKind.TIKTOK,
    "vt.tiktok.com": SourceKind.TIKTOK,
    "facebook.com": SourceKind.FACEBOOK,
    "www.facebook.com": SourceKind.FACEBOOK,
    "m.facebook.com": SourceKind.FACEBOOK,
    "mobile.facebook.com": SourceKind.FACEBOOK,
    "fb.watch": SourceKind.FACEBOOK,
    "x.com": SourceKind.X,
    "www.x.com": SourceKind.X,
    "twitter.com": SourceKind.X,
    "www.twitter.com": SourceKind.X,
    "amiami.com": SourceKind.AMIAMI,
    "www.amiami.com": SourceKind.AMIAMI,
    "nin-nin-game.com": SourceKind.NIN_NIN,
    "www.nin-nin-game.com": SourceKind.NIN_NIN,
}


def parse_w_request(text: str) -> SupportedUrl:
    command_match = _COMMAND_RE.fullmatch(text.strip())
    if command_match is None:
        raise RequestSyntaxError("expected /w followed by exactly one URL")

    original = command_match.group(1)
    try:
        parsed = urlsplit(original)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise RequestSyntaxError("malformed URL") from exc

    if not parsed.scheme or hostname is None:
        raise RequestSyntaxError("malformed URL")
    if parsed.scheme.lower() != "https":
        raise UnsupportedUrlError("only HTTPS URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise UnsupportedUrlError("URL credentials are not supported")
    if port not in (None, 443):
        raise UnsupportedUrlError("non-standard ports are not supported")

    host = _normalize_hostname(hostname)
    kind = _HOST_TO_SOURCE.get(host)
    if kind is None:
        raise UnsupportedUrlError("unsupported host")

    normalized_parts = SplitResult(
        scheme="https",
        netloc=host,
        path=parsed.path or "/",
        query=parsed.query,
        fragment="",
    )
    return SupportedUrl(
        original=original,
        normalized=urlunsplit(normalized_parts),
        kind=kind,
    )


def _normalize_hostname(hostname: str) -> str:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            return hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise UnsupportedUrlError("invalid hostname") from exc
    raise UnsupportedUrlError("IP-address URLs are not supported")
