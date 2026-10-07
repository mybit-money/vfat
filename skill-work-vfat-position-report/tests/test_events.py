from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from vfat_report.adapters.base import AdapterKey
from vfat_report.adapters.registry import get_adapter
from vfat_report.contracts import ActivityInput, PositionInput
from vfat_report.events import decode_receipt, load_chain_profile, merge_position_activity


ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_PATH = ROOT / "profiles" / "hyperevm-nest.json"


def activity_from_json(item: dict) -> ActivityInput:
    return ActivityInput(
        chain_id=item["chainId"],
        transaction_hash=item["transactionHash"],
        timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
        action_type=item["actionType"],
        source_position_ids=tuple(item["sourcePositionIds"]),
        recipient_position_id=item["recipientPositionId"],
        is_automation=item["isAutomation"],
        automation_payment_method=item["automationPaymentMethod"],
    )


class EventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_chain_profile(PROFILE_PATH)
        raw = json.loads((FIXTURES / "multi-source-activity.json").read_text(encoding="utf-8"))
        self.activities = tuple(activity_from_json(item) for item in raw)

    def test_merge_activity_deduplicates_transaction_and_sources(self) -> None:
        merged = merge_position_activity(self.activities)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_position_ids, ("nft:90822", "nft:92156"))
        self.assertEqual(merged[0].recipient_position_ids, ("nft:91811",))

    def test_fee_paid_compound_uses_observed_transfer_not_configured_rate(self) -> None:
        receipt = json.loads((FIXTURES / "fee-compound-receipt.json").read_text(encoding="utf-8"))
        activity = merge_position_activity(self.activities)[0]

        decoded = decode_receipt(activity, receipt, self.profile)

        self.assertEqual(decoded.gross_claims[0].raw_amount, 1292916846259404975117)
        self.assertEqual(decoded.automation_fees[0].raw_amount, 23272503232669289552)
        self.assertEqual(
            decoded.effective_automation_fee_rate,
            Decimal("0.01799999999999999999991801484"),
        )
        self.assertNotEqual(
            decoded.effective_automation_fee_rate,
            self.profile.expected_automation_fee_rate,
        )
        self.assertEqual(decoded.lp_additions[0].raw_amount, 86938162529835173)
        self.assertEqual(decoded.lp_additions[1].raw_amount, 38137843806486896444)
        self.assertNotIn("automation_fee_rate_differs_from_expected", decoded.warnings)

    def test_adapter_receipt_matches_legacy_decoder(self) -> None:
        receipt = json.loads((FIXTURES / "fee-compound-receipt.json").read_text(encoding="utf-8"))
        activity = merge_position_activity(self.activities)[0]
        position = PositionInput("nft:1", 999, "nest", "nft", "0x05a34ca31a38c136b8489d4147112cfc4a92a155")
        adapter = get_adapter(AdapterKey(999, "nest"))

        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.decode_receipt(activity, receipt, (position,)), decode_receipt(activity, receipt, self.profile))

    def test_gas_account_debit_is_separate_from_keeper_network_gas(self) -> None:
        receipt = json.loads((FIXTURES / "gas-account-compound-receipt.json").read_text(encoding="utf-8"))
        base = merge_position_activity(self.activities)[0]
        activity = replace(
            base,
            transaction_hash=receipt["transactionHash"],
            automation_payment_method="gas-account",
        )

        decoded = decode_receipt(activity, receipt, self.profile)

        self.assertEqual(decoded.gas_account_debit_native, Decimal("0.0002627023"))
        self.assertEqual(decoded.network_gas_native, Decimal("0.0002486184"))
        self.assertEqual(decoded.network_gas_payer, "0xb0bada5d45d939a03c6d211d24a61a4418d7cd13")
        self.assertNotEqual(decoded.gas_account_debit_native, decoded.network_gas_native)

    def test_unknown_cost_event_is_unavailable_not_zero(self) -> None:
        receipt = json.loads((FIXTURES / "gas-account-compound-receipt.json").read_text(encoding="utf-8"))
        base = merge_position_activity(self.activities)[0]
        activity = replace(
            base,
            transaction_hash=receipt["transactionHash"],
            automation_payment_method="gas-account",
        )
        profile = replace(self.profile, gas_account_debit_events=())

        decoded = decode_receipt(activity, receipt, profile)

        self.assertIsNone(decoded.gas_account_debit_native)
        self.assertIn("gas_account_debit_unavailable", decoded.warnings)

    def test_log_identity_prevents_double_counting(self) -> None:
        receipt = json.loads((FIXTURES / "fee-compound-receipt.json").read_text(encoding="utf-8"))
        receipt["logs"].append(dict(receipt["logs"][1]))
        activity = merge_position_activity(self.activities)[0]

        decoded = decode_receipt(activity, receipt, self.profile)

        self.assertEqual(len(decoded.automation_fees), 1)


if __name__ == "__main__":
    unittest.main()
