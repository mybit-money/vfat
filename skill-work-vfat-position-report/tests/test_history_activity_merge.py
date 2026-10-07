from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_history_merge import POSITION_ID, _payload
from vfat_report.contracts import load_report_input


class HistoryActivityMergeTests(unittest.TestCase):
    def test_duplicate_activity_keeps_union_of_source_positions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            primary_path = root / "current" / "input.json"
            history_path = root / "old" / "input.json"
            primary_path.parent.mkdir()
            history_path.parent.mkdir()
            tx_hash = "0x" + "c" * 64

            old = _payload("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")
            old["activities"] = [
                {
                    "chainId": 999,
                    "transactionHash": tx_hash,
                    "timestamp": "2026-10-01T12:00:00Z",
                    "actionType": "compounded",
                    "sourcePositionIds": ["manager:old"],
                }
            ]
            primary = _payload("2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z")
            primary["activities"] = [
                {
                    "chainId": 999,
                    "transactionHash": tx_hash,
                    "timestamp": "2026-10-01T12:00:00Z",
                    "actionType": "compounded",
                    "sourcePositionIds": [POSITION_ID],
                }
            ]
            history_path.write_text(json.dumps(old), encoding="utf-8")
            primary_path.write_text(json.dumps(primary), encoding="utf-8")

            actual = load_report_input(primary_path, history_root=root)

            self.assertEqual(len(actual.activities), 1)
            self.assertEqual(
                actual.activities[0].source_position_ids,
                (POSITION_ID, "manager:old"),
            )


if __name__ == "__main__":
    unittest.main()
