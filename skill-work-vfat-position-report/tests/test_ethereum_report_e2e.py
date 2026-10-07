"""Offline runner proof: lineage, complete activity, chain isolation and fail-closed income."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from vfat_report import runner
from vfat_report.cli import parse_args
from vfat_report.contracts import load_report_input
from vfat_report.adapters.hyperevm_nest import HyperEvmNestAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "ethereum-uniswap-v4"
ROOT = "bd216513d74c8cf14cf4747e6aaa6420ff64ee9e:413470"
ETH = "0x0000000000000000000000000000000000000000"
DRV = "0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
RPCS = ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com"]


def replay(output: Path, cache: Path) -> tuple[dict, str]:
    source = json.loads((FIXTURES / "input-14d.json").read_text())
    prices = json.loads((FIXTURES / "prices-14d.json").read_text())

    def rpc_transport(endpoint, payload):
        if endpoint not in RPCS or payload["method"] != "eth_getTransactionReceipt":
            raise AssertionError(f"Unexpected RPC: {endpoint} {payload}")
        tx_hash, = payload["params"]
        if tx_hash not in source["source"]["receipts"]:
            raise AssertionError(f"Unexpected receipt: {tx_hash}")
        receipt = json.loads((FIXTURES / source["source"]["receipts"][tx_hash]).read_text())
        return {"jsonrpc": "2.0", "id": payload["id"], "result": receipt}

    def price_transport(url):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "coins.llama.fi" or parsed.path != "/batchHistorical":
            raise AssertionError(f"Unexpected price URL: {url}")
        requested = json.loads(parse_qs(parsed.query)["coins"][0])
        coins = {}
        for coin, timestamps in requested.items():
            if coin not in prices["requests"] or not set(timestamps) <= set(prices["requests"][coin]):
                raise AssertionError(f"Unexpected price request: {coin} {timestamps}")
            coins[coin] = prices["response"]["coins"][coin]
        return {"coins": coins}

    args = parse_args([
        "--input", str(FIXTURES / "input-14d.json"),
        "--output-dir", str(output), "--cache-dir", str(cache),
        "--now", "2026-10-07T09:00:00Z",
    ])
    with patch("vfat_report.rpc._urllib_transport", side_effect=rpc_transport), patch(
        "vfat_report.prices._urllib_transport", side_effect=price_transport
    ), patch("urllib.request.urlopen", side_effect=AssertionError("live network forbidden")), patch.object(
        HyperEvmNestAdapter, "decode_receipt", side_effect=AssertionError("cross-adapter decoder")
    ):
        if runner.run(args) != 0:
            raise AssertionError("runner failed")
    return (json.loads((output / "report.json").read_text(encoding="utf-8")),
            (output / "report.html").read_text(encoding="utf-8"))


def stable_snapshot(report: dict) -> dict:
    return {key: report[key] for key in ("transactions", "days", "diagnostics")}


class EthereumReportEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        cls.report, cls.html = replay(root / "out", root / "cache")

    def test_report_matches_reviewed_fourteen_day_evidence(self):
        expected = json.loads((FIXTURES / "expected-report-14d.json").read_text())
        self.maxDiff = None
        self.assertEqual(stable_snapshot(self.report), expected)

    def test_all_six_compounds_keep_one_lineage_and_current_nft(self):
        source = json.loads((FIXTURES / "input-14d.json").read_text())
        parsed = load_report_input(FIXTURES / "input-14d.json")
        self.assertEqual(len(parsed.positions), 1)
        self.assertEqual(parsed.positions[0].position_id, ROOT)
        self.assertEqual(parsed.positions[0].position_root_token_id, ROOT)
        self.assertEqual(parsed.positions[0].token_id, "413473")
        evidence = json.loads((FIXTURES / "activity-lineage-evidence.json").read_text())
        in_window = {a["transactionHash"] for a in evidence["data"]
                     if "2026-09-24" <= a["blockTimestamp"] < "2026-10-08"}
        self.assertEqual(len(in_window), 6)
        self.assertEqual({t["transaction_hash"] for t in self.report["transactions"]}, in_window)
        for tx in self.report["transactions"]:
            self.assertEqual(tx["chain_id"], 1)
            self.assertEqual(tx["source_position_ids"], [ROOT])
            self.assertEqual(tx["recipient_position_ids"], [ROOT])
        rebalance = next(a for a in evidence["data"] if a["actionType"] == "rebalanced")
        self.assertEqual((rebalance["prevTokenId"], rebalance["tokenId"]), ("413470", "413473"))
        self.assertNotIn(rebalance["transactionHash"], in_window)
        self.assertEqual(len(source["capitalPoints"]), 264)
        first, second = source["capitalPoints"][:2]
        self.assertEqual((datetime.fromisoformat(second["timestamp"]) -
                          datetime.fromisoformat(first["timestamp"])).total_seconds(), 29 * 3600)

    def test_claim_fee_and_apr_fail_closed_but_compound_and_pnl_survive(self):
        for tx in self.report["transactions"]:
            self.assertIsNone(tx["gross_claim_usd"]["usd"])
            self.assertEqual(tx["gross_claim_usd"]["reason"], "native_claim_unavailable")
            self.assertIsNone(tx["automation_fee_usd"]["usd"])
            self.assertEqual(tx["automation_fee_usd"]["reason"], "native_fee_unavailable")
            self.assertTrue(tx["gross_claims"])
            self.assertTrue(tx["automation_fees"])
            self.assertTrue(tx["lp_additions"])
            self.assertIsNotNone(tx["net_compound_usd"]["usd"])
            self.assertGreater(Decimal(tx["network_gas_native"]), 0)
            self.assertIsNone(tx["gas_account_debit_native"])
        days = sorted(self.report["days"], key=lambda day: day["day"])
        self.assertEqual([d["day"] for d in days], [
            "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27",
            "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01",
            "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05",
            "2026-10-06", "2026-10-07",
        ])
        self.assertEqual(days[-1]["status"], "partial")
        self.assertEqual(sum(d["claim_transaction_count"] for d in days), 6)
        for day in days:
            self.assertIsNotNone(day["average_capital_usd"])
            self.assertIsNotNone(day["cumulative_pnl_usd"])
            self.assertIsNotNone(day["daily_pnl_usd"])
            self.assertEqual(Decimal(day["gas_account_debit_usd"]), 0)
            if day["claim_transaction_count"]:
                for metric in ("gross_claim_usd", "automation_fee_usd", "net_claim_usd", "realized_apr_percent"):
                    self.assertIsNone(day[metric])
                self.assertIn("native_claim_unavailable", day["reasons"])
                self.assertIn("native_fee_unavailable", day["reasons"])
            else:
                self.assertEqual(Decimal(day["net_compound_usd"]), 0)
                self.assertEqual(Decimal(day["realized_apr_percent"]), 0)
        self.assertEqual(self.report["diagnostics"], {"warnings": [], "reasons": [], "rpc_endpoints": RPCS})

    def test_exact_transfer_evidence_and_capital_are_not_replaced_by_estimates(self):
        # DRV amounts independently read from selected PoolManager->Sickle,
        # Sickle->fee-recipient, and Sickle->PoolManager Transfer logs.
        expected = [
            (250175301936019446169, 2251577717424175015, 388475690078593332301),
            (117750246429952785306, 2119504435739150135, 192614987228833359890),
            (54283553970900230193, 977103971476204143, 92313838643716844168),
            (178147014445389557455, 1603323130008506017, 318037572574065939902),
            (153436634871055107226, 2761859427678991930, 269803301529586295801),
            (149900950242857240585, 1349108552185715165, 284732973291841119728),
        ]
        for tx, (claim, fee, lp) in zip(self.report["transactions"], expected, strict=True):
            self.assertEqual([(x["token_address"], x["raw_amount"]) for x in tx["gross_claims"]],
                             [(DRV, claim)])
            self.assertEqual([(x["token_address"], x["raw_amount"]) for x in tx["automation_fees"]],
                             [(DRV, fee)])
            self.assertEqual(next(x["raw_amount"] for x in tx["lp_additions"]
                                  if x["token_address"] == DRV), lp)
            self.assertEqual(tx["warnings"], ["native_claim_unavailable", "native_fee_unavailable"])
        days = {d["day"]: d for d in self.report["days"]}
        # Existing LOCF semantics preserve the observed value across the 29h gap.
        self.assertEqual(days["2026-09-24"]["average_capital_usd"], "5303.838238975012")
        self.assertEqual(Decimal(days["2026-09-24"]["daily_pnl_usd"]), 0)
        self.assertEqual(days["2026-10-07"]["position_value_usd"], "5228.742011350896")
        self.assertEqual(days["2026-10-07"]["cumulative_pnl_usd"], "308.1681295650196")
        # Difference of the final and opening VFAT PnL: claims are not added again.
        self.assertEqual(sum(Decimal(d["daily_pnl_usd"]) for d in days.values()),
                         Decimal("-62.05022865824506"))

    def test_html_and_price_evidence_are_complete_for_replay(self):
        for value in ("Дата UTC", "APR net", "DRV", "2026-09-24", "2026-10-07",
                      "native_claim_unavailable", "native_fee_unavailable"):
            self.assertIn(value, self.html)
        prices = json.loads((FIXTURES / "prices-14d.json").read_text())
        self.assertEqual(set(prices["requests"]), {"ethereum:" + WETH, "ethereum:" + DRV})
        for coin, timestamps in prices["requests"].items():
            for timestamp in timestamps:
                nearest = min(abs(p["timestamp"] - timestamp)
                              for p in prices["response"]["coins"][coin]["prices"])
                self.assertLessEqual(nearest, 900)


if __name__ == "__main__":
    unittest.main()
