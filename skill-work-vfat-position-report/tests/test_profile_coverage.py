from __future__ import annotations

import unittest
from pathlib import Path

from vfat_report.events import load_chain_profile


class ProfileCoverageTests(unittest.TestCase):
    def test_ethereum_pool_has_known_underlying_assets(self) -> None:
        path = Path(__file__).parents[1] / 'profiles' / 'ethereum-uniswap-v4.json'
        self.assertTrue(path.exists(), 'Ethereum profile must exist')
        profile = load_chain_profile(path)
        self.assertEqual(profile.chain_id, 1)
        for pair in profile.pools.values():
            for token in pair:
                self.assertEqual(profile.tokens[token].decimals, 18)

    def test_default_wallet_pool_tokens_are_available_for_mint_decoding(self) -> None:
        profile = load_chain_profile(
            Path(__file__).parents[1] / "profiles" / "hyperevm-nest.json"
        )
        expected_pools = {
            "0x34a4539f9527d20985e3d14e81d8b473015acf9c",
            "0xbe512f5881b85c48d9c17bc5bb2be047d156d696",
            "0x613bc619741354a6171692b04228c9640373e54b",
            "0xdb544d63d32d9f3e52ff3a8bfe2a374df0463f8d",
        }

        self.assertTrue(expected_pools.issubset(profile.pools))
        for token0, token1 in (profile.pools[address] for address in expected_pools):
            self.assertIn(token0, profile.tokens)
            self.assertIn(token1, profile.tokens)


if __name__ == "__main__":
    unittest.main()
