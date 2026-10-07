from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .cache import ReportCache
from .contracts import NormalizedTransaction, TokenAmount, Valuation


DEFAULT_BASE_URL = "https://coins.llama.fi"
Transport = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True)
class PriceQuote:
    token_address: str
    requested_timestamp: int
    quote_timestamp: int
    price_usd: Decimal
    confidence: Decimal | None
    source: str


class DefiLlamaPriceClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: Transport | None = None,
        cache: ReportCache | None = None,
        max_batch_points: int = 50,
        max_distance_seconds: int = 15 * 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _urllib_transport
        self.cache = cache
        self.max_batch_points = max_batch_points
        self.max_distance_seconds = max_distance_seconds
        self.diagnostics: list[str] = []

    def get_quotes(
        self,
        requests: Iterable[tuple[str, datetime]],
        *,
        chain_slug: str,
    ) -> dict[tuple[str, int], PriceQuote]:
        normalized = sorted(
            {
                (address.lower(), _unix_timestamp(timestamp))
                for address, timestamp in requests
            }
        )
        quotes: dict[tuple[str, int], PriceQuote] = {}
        missing: list[tuple[str, int]] = []
        for key in normalized:
            cached = self._get_cached(key)
            if cached is None:
                missing.append(key)
            else:
                quotes[key] = cached

        for offset in range(0, len(missing), self.max_batch_points):
            batch = missing[offset : offset + self.max_batch_points]
            request_payload: dict[str, list[int]] = {}
            for address, timestamp in batch:
                request_payload.setdefault(f"{chain_slug}:{address}", []).append(timestamp)
            query = urllib.parse.urlencode(
                {"coins": json.dumps(request_payload, separators=(",", ":"))}
            )
            try:
                response = self.transport(f"{self.base_url}/batchHistorical?{query}")
            except (OSError, TimeoutError, ValueError) as error:
                self.diagnostics.append(f"price_provider_failed:{type(error).__name__}")
                continue
            response_coins = response.get("coins", {})
            for address, requested_timestamp in batch:
                coin_id = f"{chain_slug}:{address}"
                coin = response_coins.get(coin_id, {}) if isinstance(response_coins, Mapping) else {}
                prices = coin.get("prices", []) if isinstance(coin, Mapping) else []
                quote = self._nearest_quote(address, requested_timestamp, prices)
                if quote is None:
                    continue
                quotes[(address, requested_timestamp)] = quote
                self._put_cached(quote)
        return quotes

    def _nearest_quote(
        self, address: str, requested_timestamp: int, prices: Any
    ) -> PriceQuote | None:
        candidates = [item for item in prices if isinstance(item, Mapping)]
        if not candidates:
            self.diagnostics.append(f"price_quote_missing:{address}:{requested_timestamp}")
            return None
        item = min(
            candidates,
            key=lambda value: abs(int(value["timestamp"]) - requested_timestamp),
        )
        quote_timestamp = int(item["timestamp"])
        distance = abs(quote_timestamp - requested_timestamp)
        if distance > self.max_distance_seconds:
            self.diagnostics.append(
                f"price_quote_too_far:{address}:{requested_timestamp}:{distance}"
            )
            return None
        confidence = item.get("confidence")
        return PriceQuote(
            token_address=address,
            requested_timestamp=requested_timestamp,
            quote_timestamp=quote_timestamp,
            price_usd=Decimal(str(item["price"])),
            confidence=Decimal(str(confidence)) if confidence is not None else None,
            source="defillama:batchHistorical",
        )

    def _cache_key(self, key: tuple[str, int]) -> str:
        address, timestamp = key
        return f"price_{address.removeprefix('0x')}_{timestamp}"

    def _get_cached(self, key: tuple[str, int]) -> PriceQuote | None:
        if self.cache is None:
            return None
        value = self.cache.get_snapshot(self._cache_key(key))
        if value is None:
            return None
        confidence = value.get("confidence")
        return PriceQuote(
            token_address=key[0],
            requested_timestamp=key[1],
            quote_timestamp=int(value["quoteTimestamp"]),
            price_usd=Decimal(str(value["priceUsd"])),
            confidence=Decimal(str(confidence)) if confidence is not None else None,
            source=str(value["source"]),
        )

    def _put_cached(self, quote: PriceQuote) -> None:
        if self.cache is None:
            return
        self.cache.put_snapshot(
            self._cache_key((quote.token_address, quote.requested_timestamp)),
            {
                "quoteTimestamp": quote.quote_timestamp,
                "priceUsd": str(quote.price_usd),
                "confidence": str(quote.confidence) if quote.confidence is not None else None,
                "source": quote.source,
            },
        )


def collect_price_requests(
    transactions: Iterable[NormalizedTransaction],
    native_price_token: str | None,
    *,
    price_token_resolver: Callable[[str], str],
) -> tuple[tuple[str, datetime], ...]:
    requests: set[tuple[str, datetime]] = set()
    for transaction in transactions:
        for amount in (
            *transaction.gross_claims,
            *transaction.automation_fees,
            *transaction.lp_additions,
        ):
            requests.add((price_token_resolver(amount.token_address).lower(), transaction.timestamp))
        if getattr(transaction, "gas_account_debit_native", None) is not None and native_price_token:
            requests.add((price_token_resolver(native_price_token).lower(), transaction.timestamp))
    return tuple(sorted(requests, key=lambda item: (item[1], item[0])))


def value_transaction(
    transaction: NormalizedTransaction,
    quotes: Mapping[tuple[str, int], PriceQuote],
    *,
    native_price_token: str | None,
    price_token_resolver: Callable[[str], str],
) -> NormalizedTransaction:
    timestamp = _unix_timestamp(transaction.timestamp)
    gross = _value_amounts(
        transaction.gross_claims, quotes, timestamp, "historical_reward_usd_unavailable",
        price_token_resolver=price_token_resolver,
    )
    fee = _value_amounts(
        transaction.automation_fees,
        quotes,
        timestamp,
        "automation_fee_usd_unavailable",
        price_token_resolver=price_token_resolver,
        empty_is_zero=True,
    )
    net = _value_amounts(
        transaction.lp_additions, quotes, timestamp, "historical_lp_usd_unavailable",
        price_token_resolver=price_token_resolver,
    )
    # A priced balance is not income when principal and rewards are inseparable.
    # Keep the adapter's explicit accounting block while retaining raw LP evidence.
    if transaction.net_compound_usd.reason == "claim_principal_separation_unavailable":
        net = Valuation(None, reason="claim_principal_separation_unavailable")
    gas_native = getattr(transaction, "gas_account_debit_native", None)
    if gas_native is None:
        gas = transaction.gas_account_debit_usd
    elif not native_price_token:
        gas = Valuation(None, reason="native_price_token_unavailable")
    else:
        quote = quotes.get((price_token_resolver(native_price_token).lower(), timestamp))
        gas = (
            Valuation(gas_native * quote.price_usd, source=quote.source)
            if quote
            else Valuation(None, reason="historical_native_usd_unavailable")
        )
    return replace(
        transaction,
        gross_claim_usd=gross,
        automation_fee_usd=fee,
        net_compound_usd=net,
        gas_account_debit_usd=gas,
    )


def _value_amounts(
    amounts: Iterable[TokenAmount],
    quotes: Mapping[tuple[str, int], PriceQuote],
    timestamp: int,
    missing_reason: str,
    *,
    price_token_resolver: Callable[[str], str],
    empty_is_zero: bool = False,
) -> Valuation:
    items = tuple(amounts)
    if not items:
        return (
            Valuation(Decimal(0), source="onchain:no-transfer")
            if empty_is_zero
            else Valuation(None, reason=missing_reason)
        )
    total = Decimal(0)
    sources: set[str] = set()
    for amount in items:
        quote = quotes.get((price_token_resolver(amount.token_address).lower(), timestamp))
        if quote is None:
            return Valuation(None, reason=missing_reason)
        total += amount.amount * quote.price_usd
        sources.add(quote.source)
    return Valuation(total, source=",".join(sorted(sources)))


def _unix_timestamp(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("price timestamps must include a timezone")
    return int(value.astimezone(timezone.utc).timestamp())


def _urllib_transport(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "vfat-position-report/1.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("price provider response must be a JSON object")
    return value
