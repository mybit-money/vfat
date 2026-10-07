from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_history_merge import POSITION_ID, _payload
from vfat_report.contracts import load_report_input


class HistoryCompatibilityTests(unittest.TestCase):
    def test_history_root_ignores_inputs_for_another_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            primary_path = root / "current" / "input.json"
            foreign_path = root / "foreign" / "input.json"
            primary_path.parent.mkdir()
            foreign_path.parent.mkdir()

            primary = _payload("2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z")
            primary["capitalPoints"] = [
                {
                    "positionId": POSITION_ID,
                    "timestamp": "2026-10-02T00:00:00Z",
                    "currentBalanceUsd": "200",
                    "totalPnlUsd": "20",
                }
            ]
            foreign = _payload("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")
            foreign["wallet"] = "0x1111111111111111111111111111111111111111"
            foreign["capitalPoints"] = [
                {
                    "positionId": POSITION_ID,
                    "timestamp": "2026-09-01T00:00:00Z",
                    "currentBalanceUsd": "999",
                    "totalPnlUsd": "999",
                }
            ]

            primary_path.write_text(json.dumps(primary), encoding="utf-8")
            foreign_path.write_text(json.dumps(foreign), encoding="utf-8")

            actual = load_report_input(primary_path, history_root=root)

            self.assertEqual(actual.start.isoformat(), "2026-10-02T00:00:00+00:00")
            self.assertEqual(len(actual.capital_points), 1)
            self.assertEqual(actual.capital_points[0].current_balance_usd, 200)


if __name__ == "__main__":
    unittest.main()
