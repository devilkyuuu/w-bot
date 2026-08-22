from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree

from wbot.errors import RetrievalError
from wbot.extractors.common import fetch_bytes

ECB_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


class ExchangeService:
    def __init__(self) -> None:
        self._rates: dict[str, Decimal] = {"EUR": Decimal(1)}
        self._fetched_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def rates(self) -> dict[str, Decimal]:
        if self._is_fresh():
            return self._rates.copy()
        async with self._lock:
            if self._is_fresh():
                return self._rates.copy()
            try:
                document, _ = await fetch_bytes(
                    ECB_RATES_URL,
                    allowed_domains=("ecb.europa.eu",),
                    max_bytes=1_000_000,
                )
                parsed = _parse_rates(document)
            except Exception:
                if self._fetched_at is not None:
                    return self._rates.copy()
                raise RetrievalError from None
            self._rates = parsed
            self._fetched_at = datetime.now(UTC)
            return parsed.copy()

    async def convert(self, amount: Decimal, source: str, target: str) -> Decimal:
        rates = await self.rates()
        source_rate = rates.get(source.upper())
        target_rate = rates.get(target.upper())
        if source_rate is None or target_rate is None:
            raise RetrievalError
        euros = amount / source_rate
        return (euros * target_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    async def jpy_to_eur(self, price_jpy: Decimal) -> Decimal:
        return await self.convert(price_jpy, "JPY", "EUR")

    def _is_fresh(self) -> bool:
        return self._fetched_at is not None and datetime.now(UTC) - self._fetched_at < timedelta(
            hours=12
        )


def _parse_rates(document: bytes) -> dict[str, Decimal]:
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError:
        raise RetrievalError from None
    rates = {"EUR": Decimal(1)}
    for element in root.iter():
        currency = element.attrib.get("currency")
        rate = element.attrib.get("rate")
        if currency and rate:
            try:
                rates[currency.upper()] = Decimal(rate)
            except Exception:
                raise RetrievalError from None
    if "JPY" not in rates:
        raise RetrievalError
    return rates
