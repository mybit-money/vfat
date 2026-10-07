from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from vfat_report.contracts import load_report_input


WALLET = "0x330d2a845d2df4e329034d72719c7c53f9c1f87a"
SICKLE = "0x05a34ca31a38c136b8489d4147112cfc4a92a155"
POSITION_ID = "manager:1"


def _payload(start: str, end: str) -> dict:
    return {
        "schemaVersion": "1.0",
        "wallet": WALLET,
        "period": {"from": start, "to": end},
        "filters": {"chainIds": [999], "protocols": ["nest"], "rewardTokens": []},
        "positions": [
            {
                "positionId": POSITION_ID,
                "chainId": 999,
                "protocol": "nest",
                "positionType": "nft",
                "sickleAddress": SICKLE,
            }
        ],
        "activities": [],
        "capitalPoints": [],
        "source": {"provider": "vfat-mcp"},
    }


class HistoryMergeTests(unittest.TestCase):
    def test_history_root_extends_period_and_primary_values_win_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            primary_path = root / "current" / "input.json"
            history_path = root / "old" / "input.json"
            primary_path.parent.mkdir()
            history_path.parent.mkdir()

            old = _payload("2026-09-30T00:00:00Z", "2026-10-02T00:00:00Z")
            old["activities"] = [
                {
                    "chainId": 999,
                    "transactionHash": "0x" + "a" * 64,
                    "timestamp": "2026-09-30T12:00:00Z",
                    "actionType": "compounded",
                    "sourcePositionIds": [POSITION_ID],
                }
            ]
            old["capitalPoints"] = [
                {
                    "positionId": POSITION_ID,
                    "timestamp": "2026-09-30T00:00:00Z",
                    "currentBalanceUsd": "100",
                    "totalPnlUsd": "0",
                },
                {
                    "positionId": POSITION_ID,
                    "timestamp": "2026-10-02T00:00:00Z",
                    "currentBalanceUsd": "150",
                    "totalPnlUsd": "15",
                },
            ]

            primary = _payload("2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z")
            primary["activities"] = [
                {
                    "chainId": 999,
                    "transactionHash": "0x" + "b" * 64,
                    "timestamp": "2026-10-02T12:00:00Z",
                    "actionType": "compounded",
                    "sourcePositionIds": [POSITION_ID],
                }
            ]
            primary["capitalPoints"] = [
                {
                    "positionId": POSITION_ID,
                    "timestamp": "2026-10-02T00:00:00Z",
                    "currentBalanceUsd": "200",
                    "totalPnlUsd": "20",
                }
            ]

            history_path.write_text(json.dumps(old), encoding="utf-8")
            primary_path.write_text(json.dumps(primary), encoding="utf-8")

            actual = load_report_input(primary_path, history_root=root)

            self.assertEqual(actual.start.isoformat(), "2026-09-30T00:00:00+00:00")
            self.assertEqual(actual.end.isoformat(), "2026-10-03T00:00:00+00:00")
            self.assertEqual(len(actual.activities), 2)
            self.assertEqual(len(actual.capital_points), 2)
            latest = max(actual.capital_points, key=lambda point: point.timestamp)
            self.assertEqual(latest.current_balance_usd, Decimal("200"))
            self.assertEqual(latest.total_pnl_usd, Decimal("20"))


if __name__ == "__main__":
    unittest.main()
