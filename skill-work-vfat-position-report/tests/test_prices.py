from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from vfat_report.cache import ReportCache
from vfat_report.contracts import TokenAmount, Valuation
from vfat_report.events import DecodedTransaction
from vfat_report.prices import DefiLlamaPriceClient, PriceQuote, collect_price_requests, value_transaction


UTC = timezone.utc
NEST = "0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035"
WHYPE = "0x5555555555555555555555555555555555555555"
DRV = "0x9628bba16db41ea7fe1fd84f9ce53bc27c63f59b"
WALLET = "0x330d2a845d2df4e329034d72719c7c53f9c1f87a"
ETH_SENTINEL = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
NATIVE_ALIAS = "0x0000000000000000000000000000000000000000"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ETH_DRV = "0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be"


def ethereum_price_token(address: str) -> str:
    return WETH if address.lower() in (ETH_SENTINEL, NATIVE_ALIAS) else address.lower()


class PriceTests(unittest.TestCase):
    def test_batch_historical_maps_nearest_quote_and_reuses_cache(self) -> None:
        requested = datetime(2026, 10, 3, 4, 18, tzinfo=UTC)
        requested_ts = int(requested.timestamp())
        calls: list[str] = []

        def transport(url: str):
            calls.append(url)
            return {
                "coins": {
                    f"hyperliquid:{NEST}": {
                        "symbol": "NEST",
                        "prices": [{"timestamp": requested_ts - 90, "price": 0.017, "confidence": 0.99}],
                    }
                }
            }

        with tempfile.TemporaryDirectory() as temporary:
            cache = ReportCache(Path(temporary), 999, WALLET)
            client = DefiLlamaPriceClient(transport=transport, cache=cache)

            first = client.get_quotes(((NEST, requested),), chain_slug="hyperliquid")
            second = client.get_quotes(((NEST, requested),), chain_slug="hyperliquid")

        self.assertEqual(len(calls), 1)
        self.assertEqual(first, second)
        self.assertEqual(first[(NEST, requested_ts)].price_usd, Decimal("0.017"))
        self.assertEqual(first[(NEST, requested_ts)].confidence, Decimal("0.99"))
        self.assertIn("batchHistorical?coins=", calls[0])
        self.assertIn("hyperliquid%3A", calls[0])

    def test_ethereum_chain_slug_emits_ethereum_coin_id(self) -> None:
        requested = datetime(2026, 10, 3, 4, 18, tzinfo=UTC)
        requested_ts = int(requested.timestamp())
        calls: list[str] = []

        def transport(url: str):
            calls.append(url)
            return {"coins": {f"ethereum:{WETH}": {"prices": [
                {"timestamp": requested_ts, "price": 90}
            ]}}}

        quotes = DefiLlamaPriceClient(transport=transport).get_quotes(
            ((WETH, requested),), chain_slug="ethereum"
        )

        self.assertEqual(quotes[(WETH, requested_ts)].price_usd, Decimal("90"))
        self.assertIn("ethereum%3A", calls[0])

    def test_ethereum_aliases_share_weth_quote_and_preserve_raw_token_addresses(self) -> None:
        timestamp = datetime(2026, 10, 3, 4, 18, tzinfo=UTC)
        ts = int(timestamp.timestamp())
        transaction = DecodedTransaction(
            chain_id=1,
            transaction_hash="0x" + "22" * 32,
            timestamp=timestamp,
            action_type="compounded",
            gross_claims=(TokenAmount(ETH_SENTINEL, "ETH", 18, 1 * 10**18),),
            lp_additions=(
                TokenAmount(NATIVE_ALIAS, "ETH", 18, 1 * 10**18),
                TokenAmount(ETH_DRV, "DRV", 18, 10 * 10**18),
            ),
            gas_account_debit_native=Decimal("0.01"),
        )
        quotes = {
            (WETH, ts): PriceQuote(WETH, ts, ts, Decimal("90"), None, "fixture"),
            (ETH_DRV, ts): PriceQuote(ETH_DRV, ts, ts, Decimal("0.4"), None, "fixture"),
        }

        requests = collect_price_requests(
            (transaction,), ETH_SENTINEL, price_token_resolver=ethereum_price_token
        )
        valued = value_transaction(
            transaction, quotes, native_price_token=ETH_SENTINEL,
            price_token_resolver=ethereum_price_token,
        )

        self.assertEqual(requests, ((ETH_DRV, timestamp), (WETH, timestamp)))
        self.assertEqual(valued.gross_claim_usd.usd, Decimal("90"))
        self.assertEqual(valued.net_compound_usd.usd, Decimal("94.0"))
        self.assertEqual(valued.gas_account_debit_usd.usd, Decimal("0.90"))
        self.assertEqual(valued.gross_claims[0].token_address, ETH_SENTINEL)
        self.assertEqual(valued.lp_additions[0].token_address, NATIVE_ALIAS)

    def test_quote_more_than_fifteen_minutes_away_is_rejected(self) -> None:
        requested = datetime(2026, 10, 3, 4, 18, tzinfo=UTC)
        requested_ts = int(requested.timestamp())

        def transport(_url: str):
            return {
                "coins": {
                    f"hyperliquid:{NEST}": {
                        "symbol": "NEST",
                        "prices": [{"timestamp": requested_ts - 901, "price": 0.017, "confidence": 0.99}],
                    }
                }
            }

        client = DefiLlamaPriceClient(transport=transport)

        quotes = client.get_quotes(((NEST, requested),), chain_slug="hyperliquid")

        self.assertEqual(quotes, {})
        self.assertIn("price_quote_too_far", client.diagnostics[0])

    def test_transaction_valuation_uses_claim_fee_lp_and_native_proxy(self) -> None:
        timestamp = datetime(2026, 10, 3, 4, 18, tzinfo=UTC)
        ts = int(timestamp.timestamp())
        transaction = DecodedTransaction(
            chain_id=999,
            transaction_hash="0x" + "11" * 32,
            timestamp=timestamp,
            action_type="compounded",
            gross_claims=(TokenAmount(NEST, "NEST", 18, 100 * 10**18),),
            automation_fees=(TokenAmount(NEST, "NEST", 18, 2 * 10**18),),
            lp_additions=(
                TokenAmount(WHYPE, "WHYPE", 18, 1 * 10**18),
                TokenAmount(DRV, "DRV", 18, 10 * 10**18),
            ),
            gross_claim_usd=Valuation(None, reason="historical_reward_usd_unavailable"),
            net_compound_usd=Valuation(None, reason="historical_lp_usd_unavailable"),
            gas_account_debit_usd=Valuation(None, reason="historical_native_usd_unavailable"),
            gas_account_debit_native=Decimal("0.01"),
        )
        quotes = {
            (NEST, ts): PriceQuote(NEST, ts, ts, Decimal("0.02"), Decimal("0.99"), "defillama"),
            (WHYPE, ts): PriceQuote(WHYPE, ts, ts, Decimal("90"), Decimal("0.99"), "defillama"),
            (DRV, ts): PriceQuote(DRV, ts, ts, Decimal("0.4"), Decimal("0.99"), "defillama"),
        }

        valued = value_transaction(
            transaction, quotes, native_price_token=WHYPE,
            price_token_resolver=str.lower,
        )

        self.assertEqual(valued.gross_claim_usd.usd, Decimal("2.00"))
        self.assertEqual(valued.automation_fee_usd.usd, Decimal("0.04"))
        self.assertEqual(valued.net_compound_usd.usd, Decimal("94.0"))
        self.assertEqual(valued.gas_account_debit_usd.usd, Decimal("0.90"))
        self.assertIn("defillama", valued.net_compound_usd.source or "")


if __name__ == "__main__":
    unittest.main()
