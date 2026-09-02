from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path


class SourceKind(Enum):
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"
    X = "x"
    AMIAMI = "amiami"
    NIN_NIN = "nin_nin"


@dataclass(frozen=True, slots=True)
class SupportedUrl:
    original: str
    normalized: str
    kind: SourceKind


@dataclass(frozen=True, slots=True)
class MediaAsset:
    path: Path
    mime_type: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class VideoResult:
    asset: MediaAsset
    caption: str | None = None


@dataclass(frozen=True, slots=True)
class ProductResult:
    name: str
    manufacturer: str | None
    price_jpy: Decimal
    images: tuple[MediaAsset, ...]
    translated_name: str | None = None


@dataclass(frozen=True, slots=True)
class PostResult:
    author_name: str
    author_handle: str
    text: str
    photos: tuple[MediaAsset, ...] = ()
    video: MediaAsset | None = None


Result = VideoResult | ProductResult | PostResult
