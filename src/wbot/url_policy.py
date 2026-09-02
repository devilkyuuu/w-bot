from __future__ import annotations

import ipaddress
import re
from urllib.parse import SplitResult, parse_qs, urlsplit, urlunsplit

from wbot.domain import SourceKind, SupportedUrl


class RequestSyntaxError(ValueError):
    """Raised when a message does not contain exactly one standalone URL."""


class UnsupportedUrlError(ValueError):
    """Raised when a URL is unsupported or unsafe."""


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


def parse_media_request(text: str) -> SupportedUrl:
    parts = text.strip().split()
    if len(parts) != 1:
        raise RequestSyntaxError("expected exactly one standalone URL")

    original = parts[0]
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
    if not _has_supported_shape(kind, host, parsed):
        raise UnsupportedUrlError("unsupported page")

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


def _has_supported_shape(kind: SourceKind, host: str, parsed: SplitResult) -> bool:
    path = parsed.path or "/"

    if kind is SourceKind.X:
        return re.fullmatch(r"/(?:[^/]+/status|i/web/status)/\d+/?", path) is not None

    if kind is SourceKind.AMIAMI:
        code = parse_qs(parsed.query).get("gcode", [""])[0]
        return (
            path.rstrip("/") == "/eng/detail"
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", code) is not None
        )

    if kind is SourceKind.NIN_NIN:
        return re.search(r"/\d+[^/]*\.html/?$", path, flags=re.IGNORECASE) is not None

    if kind is SourceKind.TIKTOK:
        if host in {"vm.tiktok.com", "vt.tiktok.com"}:
            return re.fullmatch(r"/[^/]+/?", path) is not None
        return re.fullmatch(r"/(?:t/[^/]+|@[^/]+/video/\d+)/?", path) is not None

    if kind is SourceKind.FACEBOOK:
        if host == "fb.watch":
            return re.fullmatch(r"/[^/]+/?", path) is not None
        query = parse_qs(parsed.query)
        if path.rstrip("/") in {"/watch", "/video.php"} and query.get("v", [""])[0]:
            return True
        return any(
            re.fullmatch(pattern, path) is not None
            for pattern in (
                r"/(?:reel|reels)/[^/]+/?",
                r"/[^/]+/videos/[^/]+/?",
                r"/share/v/[^/]+/?",
            )
        )

    return False
