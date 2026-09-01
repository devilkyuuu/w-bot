from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from wbot.domain import SourceKind, SupportedUrl
from wbot.extractors.amiami import AmiAmiExtractor, _from_html
from wbot.workspace import JobWorkspace


def test_japanese_product_page_yields_sale_price_maker_and_full_gallery() -> None:
    page = """
    <html>
      <head>
        <meta property="og:title" content="ファイナルファンタジーVIIリバース
              PLAY ARTS真 セフィロス[スクウェア・エニックス]">
      </head>
      <body>
        <script>
          sname_simple = 'ファイナルファンタジーVIIリバース PLAY ARTS真 セフィロス';
          maker_name = 'スクウェア・エニックス';
        </script>
        <div>参考価格 31,900円(税込)</div>
        <div>販売価格 10%OFF 28,710円(税込)</div>
        <img src="https://img.amiami.jp/images/product/main/263/FIGURE-207185.jpg">
        <img src="https://img.amiami.jp/images/product/thumb300/263/FIGURE-207185.jpg">
        <script>
          append_item.push('https://img.amiami.jp/images/product/review/263/FIGURE-207185_01.jpg');
          append_item.push('https://img.amiami.jp/images/product/review/263/FIGURE-207185_02.jpg');
          append_item.push('https://img.amiami.jp/images/product/review/263/FIGURE-207185_03.jpg');
          append_item.push('https://img.amiami.jp/images/product/review/263/FIGURE-207185_04.jpg');
          append_item.push('https://img.amiami.jp/images/product/review/263/FIGURE-207185_05.jpg');
        </script>
      </body>
    </html>
    """.encode()

    title, maker, price, images = _from_html(
        page,
        "https://www.amiami.jp/top/detail/detail?gcode=FIGURE-207185",
    )

    assert title == "ファイナルファンタジーVIIリバース PLAY ARTS真 セフィロス"
    assert maker == "スクウェア・エニックス"
    assert price == Decimal("28710")
    assert images == [
        "https://img.amiami.jp/images/product/main/263/FIGURE-207185.jpg",
        "https://img.amiami.jp/images/product/review/263/FIGURE-207185_01.jpg",
        "https://img.amiami.jp/images/product/review/263/FIGURE-207185_02.jpg",
        "https://img.amiami.jp/images/product/review/263/FIGURE-207185_03.jpg",
        "https://img.amiami.jp/images/product/review/263/FIGURE-207185_04.jpg",
        "https://img.amiami.jp/images/product/review/263/FIGURE-207185_05.jpg",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("maker_japanese", "maker_english"),
    [
        ("スクウェア・エニックス", "Square Enix"),
        ("グッドスマイルカンパニー", "Good Smile Company"),
    ],
)
async def test_global_link_fetches_matching_japanese_page_and_caps_album(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    maker_japanese: str,
    maker_english: str,
) -> None:
    japanese_page = f"""
    <meta property="og:title" content="商品名[{maker_japanese}]">
    <script>sname_simple = '商品名'; maker_name = '{maker_japanese}';</script>
    <div>販売価格 1,234円(税込)</div>
    <script>
      append_item.push('https://img.amiami.jp/images/product/main/123/FIGURE-1.jpg');
      append_item.push('https://img.amiami.jp/images/product/review/123/FIGURE-1_01.jpg');
      append_item.push('https://img.amiami.jp/images/product/review/123/FIGURE-1_02.jpg');
      append_item.push('https://img.amiami.jp/images/product/review/123/FIGURE-1_03.jpg');
      append_item.push('https://img.amiami.jp/images/product/review/123/FIGURE-1_04.jpg');
      append_item.push('https://img.amiami.jp/images/product/review/123/FIGURE-1_05.jpg');
    </script>
    """.encode()
    requested_pages: list[tuple[str, tuple[str, ...]]] = []

    async def fake_fetch_bytes(
        url: str,
        *,
        allowed_domains: tuple[str, ...],
        **kwargs: Any,
    ) -> tuple[bytes, str]:
        del kwargs
        requested_pages.append((url, allowed_domains))
        if url != "https://www.amiami.jp/top/detail/detail?gcode=FIGURE-1":
            raise AssertionError(f"unexpected metadata URL: {url}")
        return japanese_page, "text/html"

    async def fake_download_asset(
        url: str,
        destination: Path,
        **kwargs: Any,
    ) -> tuple[Path, str]:
        del url, kwargs
        destination.write_bytes(b"image")
        return destination, "image/jpeg"

    monkeypatch.setattr("wbot.extractors.amiami.fetch_bytes", fake_fetch_bytes)
    monkeypatch.setattr("wbot.extractors.amiami.download_asset", fake_download_asset)
    url = SupportedUrl(
        original="https://www.amiami.com/eng/detail?gcode=FIGURE-1",
        normalized="https://www.amiami.com/eng/detail?gcode=FIGURE-1",
        kind=SourceKind.AMIAMI,
    )

    async with JobWorkspace.create(tmp_path / "media", 10_000_000) as workspace:
        product = await AmiAmiExtractor().extract(url, workspace)

    metadata_requests = [
        request for request in requested_pages if request[1] == ("amiami.jp",)
    ]
    assert metadata_requests == [
        (
            "https://www.amiami.jp/top/detail/detail?gcode=FIGURE-1",
            ("amiami.jp",),
        )
    ]
    assert product.name == "商品名"
    assert product.manufacturer == maker_english
    assert product.price_jpy == Decimal("1234")
    assert len(product.images) == 5
    assert product.translated_name is None


@pytest.mark.asyncio
async def test_title_translation_is_reused_for_the_same_product_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    japanese_page = """
    <script>
      sname_simple = 'ファイナルファンタジーVIIリバース PLAY ARTS真 セフィロス';
      maker_name = 'スクウェア・エニックス';
      append_item.push('https://img.amiami.jp/images/product/main/263/FIGURE-207185.jpg');
    </script>
    <div>販売価格 28,710円(税込)</div>
    """.encode()
    translation_requests = 0

    async def fake_fetch_bytes(
        url: str,
        *,
        allowed_domains: tuple[str, ...],
        **kwargs: Any,
    ) -> tuple[bytes, str]:
        nonlocal translation_requests
        del allowed_domains, kwargs
        if url.startswith("https://www.amiami.jp/"):
            return japanese_page, "text/html"
        if url.startswith("https://api.mymemory.translated.net/get?"):
            translation_requests += 1
            return (
                json.dumps(
                    {
                        "responseStatus": 200,
                        "responseData": {
                            "translatedText": (
                                "Final Fantasy VII Rebirth PLAY ARTS "
                                "&lt;True&gt; Sephiroth"
                            )
                        },
                    }
                ).encode(),
                "application/json",
            )
        raise AssertionError(f"unexpected URL: {url}")

    async def fake_download_asset(
        url: str,
        destination: Path,
        **kwargs: Any,
    ) -> tuple[Path, str]:
        del url, kwargs
        destination.write_bytes(b"image")
        return destination, "image/jpeg"

    monkeypatch.setattr("wbot.extractors.amiami.fetch_bytes", fake_fetch_bytes)
    monkeypatch.setattr("wbot.extractors.amiami.download_asset", fake_download_asset)
    url = SupportedUrl(
        original="https://www.amiami.com/eng/detail?gcode=FIGURE-207185",
        normalized="https://www.amiami.com/eng/detail?gcode=FIGURE-207185",
        kind=SourceKind.AMIAMI,
    )
    extractor = AmiAmiExtractor()

    async with JobWorkspace.create(tmp_path / "first", 10_000_000) as workspace:
        first = await extractor.extract(url, workspace)
    async with JobWorkspace.create(tmp_path / "second", 10_000_000) as workspace:
        second = await extractor.extract(url, workspace)

    expected = "Final Fantasy VII Rebirth PLAY ARTS <True> Sephiroth"
    assert first.translated_name == expected
    assert second.translated_name == expected
    assert translation_requests == 1
