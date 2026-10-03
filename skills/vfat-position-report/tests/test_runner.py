from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from vfat_report.contracts import PositionInput
from vfat_report.events import load_chain_profile
from vfat_report.runner import profile_for_positions


class RunnerProfileTests(unittest.TestCase):
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

        actual = profile_for_positions(profile, (position,))

        self.assertEqual(actual.tracked_sickle_addresses, frozenset({other_sickle}))
        self.assertEqual(
            replace(actual, tracked_sickle_addresses=profile.tracked_sickle_addresses),
            profile,
        )


if __name__ == "__main__":
    unittest.main()
