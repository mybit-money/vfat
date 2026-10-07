from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from vfat_report.adapters.base import AdapterKey, ReportAdapter
from vfat_report.adapters.hyperevm_nest import HyperEvmNestAdapter
from vfat_report.adapters.registry import get_adapter
from vfat_report.contracts import PositionInput
from vfat_report.events import load_chain_profile
from vfat_report.runner import profile_for_positions


class RunnerProfileTests(unittest.TestCase):
    def test_hyperevm_nest_adapter_is_registered_with_existing_defaults(self) -> None:
        adapter = get_adapter(AdapterKey(999, "nest"))

        self.assertIsNotNone(adapter)

        self.assertIsInstance(adapter, HyperEvmNestAdapter)
        self.assertIsInstance(adapter, ReportAdapter)
        self.assertEqual(adapter.key, AdapterKey(999, "nest"))
        self.assertEqual(adapter.default_rpc_endpoints, ("https://rpc.hyperliquid.xyz/evm", "https://rpc.hypurrscan.io"))
        self.assertEqual(adapter.price_chain_slug, "hyperliquid")
        self.assertEqual(adapter.normalize_price_token("0xABC"), "0xabc")

    def test_tracked_sickles_come_from_current_positions(self) -> None:
        profile_path = Path(__file__).parents[1] / "profiles" / "hyperevm-nest.json"
        profile = load_chain_profile(profile_path)
        other_sickle = "0x1111111111111111111111111111111111111111"
        position = PositionInput(
            position_id="manager:1",
            chain_id=999,
            protocol="nest",
            position_type="nft",
            sickle_address=other_sickle,
        )

        adapter = get_adapter(AdapterKey(999, "nest"))
        self.assertIsNotNone(adapter)
        self.assertTrue(adapter.supports_position(position))
        actual = adapter.profile_for_positions((position,))

        self.assertEqual(actual.tracked_sickle_addresses, frozenset({other_sickle}))
        self.assertEqual(profile_for_positions(profile, (position,)), actual)
        self.assertEqual(
            replace(actual, tracked_sickle_addresses=profile.tracked_sickle_addresses),
            profile,
        )


if __name__ == "__main__":
    unittest.main()
