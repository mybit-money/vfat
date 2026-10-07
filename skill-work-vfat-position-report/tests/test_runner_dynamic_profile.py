from __future__ import annotations

import unittest
from pathlib import Path

from vfat_report.contracts import PositionInput
from vfat_report.events import load_chain_profile
from vfat_report.runner import profile_for_positions


class DynamicProfileTests(unittest.TestCase):
    def test_position_metadata_extends_pool_and_token_decoding(self) -> None:
        profile = load_chain_profile(
            Path(__file__).parents[1] / "profiles" / "hyperevm-nest.json"
        )
        pool = "0x2222222222222222222222222222222222222222"
        token0 = "0x3333333333333333333333333333333333333333"
        token1 = "0x4444444444444444444444444444444444444444"
        position = PositionInput(
            position_id="manager:1",
            chain_id=999,
            protocol="nest",
            position_type="nft",
            sickle_address="0x1111111111111111111111111111111111111111",
            metadata={
                "poolAddress": pool,
                "underlying": [
                    {"address": token0, "symbol": "AAA", "decimals": 6},
                    {"address": token1, "symbol": "BBB", "decimals": 18},
                ],
            },
        )

        actual = profile_for_positions(profile, (position,))

        self.assertEqual(actual.pools[pool], (token0, token1))
        self.assertEqual(actual.tokens[token0].symbol, "AAA")
        self.assertEqual(actual.tokens[token0].decimals, 6)
        self.assertEqual(actual.tokens[token1].symbol, "BBB")


if __name__ == "__main__":
    unittest.main()
