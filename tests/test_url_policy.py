import pytest

from wbot.domain import SourceKind
from wbot.url_policy import RequestSyntaxError, UnsupportedUrlError, parse_media_request


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("https://www.tiktok.com/@alice/video/123", SourceKind.TIKTOK),
        ("https://vm.tiktok.com/abc123/", SourceKind.TIKTOK),
        ("https://www.facebook.com/watch/?v=123", SourceKind.FACEBOOK),
        ("https://fb.watch/abc123/", SourceKind.FACEBOOK),
        ("https://x.com/alice/status/123", SourceKind.X),
        ("https://twitter.com/alice/status/123", SourceKind.X),
        (
            "https://www.amiami.com/eng/detail?gcode=FIGURE-207185",
            SourceKind.AMIAMI,
        ),
        (
            "https://www.nin-nin-game.com/en/nendoroid/254320-product.html",
            SourceKind.NIN_NIN,
        ),
    ],
)
def test_supported_https_hosts_are_routed(text: str, kind: SourceKind) -> None:
    assert parse_media_request(text).kind is kind


def test_surrounding_whitespace_is_accepted() -> None:
    result = parse_media_request("  https://x.com/alice/status/123  ")

    assert result.kind is SourceKind.X


@pytest.mark.parametrize(
    "text",
    [
        "/w",
        "/w    ",
        "/w https://x.com/alice/status/123",
        "/w@MyPrivateBot https://x.com/alice/status/123",
        "/watch https://x.com/alice/status/123",
        "https://x.com/a/status/1 https://x.com/b/status/2",
        "Alice shared https://x.com/a/status/1",
        "not-a-url",
    ],
)
def test_missing_malformed_or_multiple_arguments_are_rejected(text: str) -> None:
    with pytest.raises(RequestSyntaxError):
            parse_media_request(text)


@pytest.mark.parametrize(
    "url",
    [
        "http://x.com/alice/status/123",
        "https://amiami.com.evil.test/eng/detail?gcode=FIGURE-207185",
        "https://evilamiami.com/eng/detail?gcode=FIGURE-207185",
        "https://user:password@x.com/alice/status/123",
        "https://127.0.0.1/x.com",
        "https://[::1]/x.com",
        "https://x.com:444/alice/status/123",
        "https://example.com/video/123",
    ],
)
def test_unsafe_or_unsupported_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsupportedUrlError):
        parse_media_request(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/home",
        "https://twitter.com/alice",
        "https://www.amiami.com/eng/detail",
        "https://www.amiami.com/eng/detail?gcode=../../secret",
        "https://www.nin-nin-game.com/en/",
        "https://www.tiktok.com/",
        "https://www.facebook.com/",
    ],
)
def test_supported_hosts_with_unsupported_page_shapes_are_rejected(url: str) -> None:
    with pytest.raises(UnsupportedUrlError):
        parse_media_request(url)


def test_normalized_url_drops_fragment_and_lowercases_host() -> None:
    result = parse_media_request("https://X.COM/Alice/status/123?lang=en#private-fragment")

    assert result.normalized == "https://x.com/Alice/status/123?lang=en"
