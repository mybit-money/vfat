from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from vfat_report.adapters.base import AdapterKey
from vfat_report.adapters.registry import get_adapter
from vfat_report.aggregate import build_report
from vfat_report.capital import aggregate_daily_capital
from vfat_report.contracts import CapitalPoint, Diagnostics, PositionInput, ReportInput, report_to_dict
from vfat_report.events import MergedActivity, decode_receipt, load_chain_profile
from vfat_report.html_report import render_html
from vfat_report.prices import PriceQuote, value_transaction


ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
UTC = timezone.utc
NEST = "0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035"
WHYPE = "0x5555555555555555555555555555555555555555"
DRV = "0x9628bba16db41ea7fe1fd84f9ce53bc27c63f59b"
SICKLE = "0x05a34ca31a38c136b8489d4147112cfc4a92a155"
RPC_ENDPOINTS = ("https://rpc.hyperliquid.xyz/evm", "https://rpc.hypurrscan.io")


def golden_snapshot() -> dict:
    capital_fixture = json.loads((FIXTURES / "capital-history.json").read_text(encoding="utf-8"))
    if capital_fixture["timezone"] != "UTC":
        raise ValueError("capital fixture must use UTC")
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = datetime(2026, 10, 2, tzinfo=UTC)
    position = PositionInput("nft:1", 999, "nest", "nft", SICKLE, active_from=start)
    points = (
        CapitalPoint("nft:1", start, Decimal("1000"), Decimal("10")),
        CapitalPoint("nft:1", datetime(2026, 10, 1, 12, tzinfo=UTC), Decimal("1100"), Decimal("20")),
        CapitalPoint("nft:1", end, Decimal("1200"), Decimal("30")),
    )
    transactions = []
    profile = load_chain_profile(ROOT / "profiles" / "hyperevm-nest.json")
    adapter = get_adapter(AdapterKey(999, "nest"))
    if adapter is None:
        raise AssertionError("HyperEVM NEST adapter is not registered")
    for filename, hour, payment_method in (
        ("fee-compound-receipt.json", 12, "fee"),
        ("gas-account-compound-receipt.json", 18, "gas-account"),
    ):
        receipt = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
        timestamp = datetime(2026, 10, 1, hour, tzinfo=UTC)
        activity = MergedActivity(
            chain_id=999,
            transaction_hash=receipt["transactionHash"],
            timestamp=timestamp,
            action_type="compounded",
            source_position_ids=("nft:1",),
            recipient_position_ids=("nft:1",),
            is_automation=True,
            automation_payment_method=payment_method,
        )
        decoded = adapter.decode_receipt(activity, receipt, (position,))
        if decoded != decode_receipt(activity, receipt, profile):
            raise AssertionError("adapter receipt differs from legacy decoder")
        requested = int(timestamp.timestamp())
        quotes = {
            (address, requested): PriceQuote(address, requested, requested, price, None, "fixture")
            for address, price in ((NEST, Decimal("0.1")), (WHYPE, Decimal("40")), (DRV, Decimal("0.5")))
        }
        transactions.append(value_transaction(
            decoded, quotes, native_price_token=WHYPE,
            price_token_resolver=adapter.normalize_price_token,
        ))
    report_input = ReportInput(
        schema_version="1.0",
        wallet="0x330d2a845d2df4e329034d72719c7c53f9c1f87a",
        start=start,
        end=end,
        chain_ids=(999,),
        protocols=("nest",),
        reward_tokens=(NEST,),
        positions=(position,),
        activities=(),
        capital_points=points,
        source={},
    )
    capital = aggregate_daily_capital((position,), points, start, end)
    report = build_report(report_input, transactions, capital, Diagnostics((), (), RPC_ENDPOINTS))
    serialized = report_to_dict(report)
    html = render_html(report)
    return {
        "transactions": serialized["transactions"],
        "days": serialized["days"],
        "diagnostics": serialized["diagnostics"],
        "htmlFacts": {
            "hasDateHeader": "Дата UTC" in html,
            "hasAprHeader": "APR net" in html,
            "hasReportDay": "2026-10-01" in html,
            "hasRewardSymbol": "NEST" in html,
            "hasCapitalAxis": 'data-axis="capital"' in html,
            "hasCapitalValue": "<td>1050.00</td>" in html,
            "hasGrossClaimValue": "<td>129.69</td>" in html,
            "hasAprValue": "<td>785.77%</td>" in html,
        },
    }


class HyperEvmGoldenTests(unittest.TestCase):
    def test_existing_receipts_and_capital_report_are_frozen(self) -> None:
        expected = json.loads((FIXTURES / "hyperevm-golden-report.json").read_text(encoding="utf-8"))
        actual = golden_snapshot()
        self.maxDiff = None
        self.assertEqual(actual, expected)
        self.assertEqual(actual["transactions"][0]["gross_claims"][0]["raw_amount"], 1292916846259404975117)
        self.assertEqual(actual["transactions"][0]["automation_fees"][0]["raw_amount"], 23272503232669289552)
        self.assertEqual(actual["transactions"][0]["effective_automation_fee_rate"], "0.01799999999999999999991801484")


if __name__ == "__main__":
    unittest.main()
