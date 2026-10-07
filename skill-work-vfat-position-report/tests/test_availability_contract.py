"""Evidence gaps stay unavailable independently of adapter reason vocabulary."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from vfat_report import runner
from vfat_report.adapters.base import unavailable_transaction
from vfat_report.adapters.hyperevm_nest import HyperEvmNestAdapter
from vfat_report.cli import parse_args
from vfat_report.contracts import TokenAmount, Valuation
from vfat_report.events import merge_position_activity
from vfat_report.prices import PriceQuote, value_transaction
from tests import test_runner_adapters
from tests.test_runner_adapters import (
    START, END, FIXTURES, ethereum_position,
    nest_position, report_input,
)


METRICS = ("gross_claim_usd", "automation_fee_usd", "net_compound_usd",
           "gas_account_debit_usd")


class AvailabilityContractTests(unittest.TestCase):
    run_input = test_runner_adapters.RunnerAdapterTests.run_input

    def test_unknown_adapter_evidence_gap_cannot_be_replaced_by_partial_prices(self):
        data = report_input(nest_position())
        tx = unavailable_transaction(merge_position_activity(data.activities)[0],
                                     "future_adapter_incomplete_settlement")
        token = "0x" + "ab" * 20
        raw = (TokenAmount(token, "TEST", 18, 2 * 10**18),)
        tx = replace(tx, gross_claims=raw, automation_fees=raw, lp_additions=raw,
                     gas_account_debit_native=Decimal("2"))
        stamp = int(tx.timestamp.timestamp())
        quotes = {(token, stamp): PriceQuote(token, stamp, stamp, Decimal("3"), None, "fixture")}

        valued = value_transaction(tx, quotes, native_price_token=token,
                                   price_token_resolver=str.lower)

        for metric in METRICS:
            with self.subTest(metric=metric):
                self.assertIsNone(getattr(valued, metric).usd)
                self.assertEqual(getattr(valued, metric).reason,
                                 "future_adapter_incomplete_settlement")
        self.assertEqual(valued.gross_claims, raw)

    def test_missing_price_remains_recoverable_when_evidence_is_complete(self):
        data = report_input(nest_position())
        tx = unavailable_transaction(merge_position_activity(data.activities)[0], "ignored")
        token = "0x" + "ab" * 20
        raw = (TokenAmount(token, "TEST", 18, 2 * 10**18),)
        tx = replace(tx, gross_claims=raw, automation_fees=raw, lp_additions=raw,
                     gas_account_debit_native=Decimal("2"),
                     **{metric: Valuation(None, reason="price_pending") for metric in METRICS})
        missing = value_transaction(tx, {}, native_price_token=token, price_token_resolver=str.lower)
        stamp = int(tx.timestamp.timestamp())
        quotes = {(token, stamp): PriceQuote(token, stamp, stamp, Decimal("3"), None, "fixture")}
        valued = value_transaction(missing, quotes, native_price_token=token,
                                   price_token_resolver=str.lower)
        for metric in METRICS:
            self.assertIsNone(getattr(missing, metric).usd)
            self.assertEqual(getattr(valued, metric).usd, Decimal("6"))

    def test_new_adapter_reason_reaches_daily_metrics_without_generic_reason_list(self):
        data = report_input(nest_position(), action_type="rebalanced")
        tx = unavailable_transaction(merge_position_activity(data.activities)[0],
                                     "future_adapter_incomplete_settlement")
        with patch.object(HyperEvmNestAdapter, "decode_receipt", return_value=tx):
            output, _ = self.run_input(data, receipt={"transactionHash": tx.transaction_hash})
        day = output["days"][0]
        self.assertIn("future_adapter_incomplete_settlement", day["reasons"])
        for metric in (*METRICS, "net_claim_usd", "realized_apr_percent"):
            self.assertIsNone(day[metric])

    def test_blocked_price_requests_exclude_partial_amounts(self):
        from vfat_report.prices import collect_price_requests

        data = report_input(nest_position())
        tx = unavailable_transaction(merge_position_activity(data.activities)[0], "future_gap")
        token = "0x" + "ab" * 20
        raw = (TokenAmount(token, "TEST", 18, 10**18),)
        tx = replace(tx, gross_claims=raw, automation_fees=raw, lp_additions=raw,
                     gas_account_debit_native=Decimal("2"))
        self.assertEqual(collect_price_requests((tx,), token, price_token_resolver=str.lower), ())
        valued = value_transaction(
            tx, {}, native_price_token=token,
            price_token_resolver=lambda address: self.fail("blocked evidence reached price resolver"),
        )
        self.assertEqual(valued, tx)

    def test_log_transaction_mismatch_on_rebalance_blocks_every_daily_metric(self):
        data = report_input(ethereum_position(), "rebalance-413470-413473", "rebalanced")
        receipt = json.loads((FIXTURES / "rebalance-413470-413473-receipt.json").read_text())
        receipt["logs"][0]["transactionHash"] = "0x" + "ab" * 32
        output, _ = self.run_input(data, receipt=receipt)
        day = output["days"][0]
        self.assertEqual(output["transactions"][0]["gross_claim_usd"]["reason"],
                         "log_transaction_mismatch")
        for metric in (*METRICS, "net_claim_usd", "realized_apr_percent"):
            with self.subTest(metric=metric):
                self.assertIsNone(day[metric])
        self.assertIn("log_transaction_mismatch", day["reasons"])

    def test_missing_receipt_on_rebalance_does_not_claim_zero_gas_debit(self):
        data = report_input(nest_position(), action_type="rebalanced")
        output, _ = self.run_input(data)
        self.assertIsNone(output["days"][0]["gas_account_debit_usd"])
        self.assertIn("receipt_unavailable", output["days"][0]["reasons"])

    def test_unavailable_annotations_use_exact_half_open_period(self):
        data = replace(report_input(nest_position(), action_type="rebalanced"),
                       start=START.replace(hour=6), end=END.replace(hour=6))
        for timestamp, blocked in ((START.replace(hour=5), False),
                                   (START.replace(hour=6), True),
                                   (END.replace(hour=5), True),
                                   (END.replace(hour=6), False),
                                   (END.replace(hour=7), False)):
            with self.subTest(timestamp=timestamp):
                scoped = replace(data, activities=(replace(data.activities[0], timestamp=timestamp),))
                output, _ = self.run_input(scoped)
                day = next(day for day in output["days"] if day["day"] == timestamp.date().isoformat())
                self.assertEqual("receipt_unavailable" in day["reasons"], blocked)
                if not blocked:
                    for metric in (*METRICS, "net_claim_usd", "realized_apr_percent"):
                        self.assertEqual(Decimal(day[metric]), 0)

    def test_history_root_outside_activity_does_not_poison_partial_days(self):
        payload = json.loads((FIXTURES.parent / "minimal-input.json").read_text())
        payload["period"] = {"from": "2026-10-02T06:00:00Z", "to": "2026-10-03T06:00:00Z"}
        payload["capitalPoints"] = [{"positionId": "nft:91811", "timestamp": timestamp,
                                     "currentBalanceUsd": "1000", "totalPnlUsd": "10"}
                                    for timestamp in ("2026-10-02T00:00:00Z", "2026-10-03T06:00:00Z")]
        history = json.loads(json.dumps(payload))
        history["activities"] = [{"chainId": 999, "transactionHash": "0x" + pair * 32,
                                  "timestamp": timestamp, "actionType": "rebalanced",
                                  "sourcePositionIds": ["nft:91811"]}
                                 for pair, timestamp in (("ab", "2026-10-02T05:00:00Z"),
                                                         ("cd", "2026-10-03T07:00:00Z"))]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "primary.json"
            primary.write_text(json.dumps(payload))
            saved = root / "history" / "input.json"
            saved.parent.mkdir()
            saved.write_text(json.dumps(history))
            args = parse_args(["--input", str(primary), "--history-root", str(saved.parent),
                               "--output-dir", str(root / "out"), "--cache-dir", str(root / "cache"),
                               "--no-prices"])
            with patch("vfat_report.rpc._urllib_transport", return_value={"result": None}):
                self.assertEqual(runner.run(args), 0)
            output = json.loads((root / "out" / "report.json").read_text())
        self.assertEqual(len(output["transactions"]), 2)
        self.assertEqual(output["inputSummary"]["from"], "2026-10-02T06:00:00Z")
        for day in output["days"]:
            self.assertNotIn("receipt_unavailable", day["reasons"])
            self.assertEqual(Decimal(day["gross_claim_usd"]), 0)

    def test_invalid_lineage_root_is_rejected_before_rpc(self):
        payload = json.loads((FIXTURES.parent / "minimal-input.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "input.json"
            args = parse_args(["--input", str(path), "--output-dir", str(root / "out"),
                               "--cache-dir", str(root / "cache"), "--no-prices"])
            for invalid in (413470, {}, [], True):
                with self.subTest(invalid=invalid):
                    payload["positions"][0]["positionRootTokenId"] = invalid
                    path.write_text(json.dumps(payload))
                    with patch.object(runner, "JsonRpcClient", side_effect=AssertionError("RPC before validation")):
                        with self.assertRaisesRegex(ValueError, "positionRootTokenId.*string or null"):
                            runner.run(args)
