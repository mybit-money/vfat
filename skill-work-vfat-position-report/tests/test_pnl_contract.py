from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from vfat_report.capital import aggregate_daily_capital
from vfat_report.contracts import CapitalPoint, PositionInput, load_report_input


UTC = timezone.utc
SICKLE = "0x05a34ca31a38c136b8489d4147112cfc4a92a155"


class PnlContractTests(unittest.TestCase):
    def test_loads_total_pnl_on_capital_points(self) -> None:
        payload = {
            "schemaVersion": "1.0",
            "positions": [],
            "capitalPoints": [{
                "positionId": "nft:91811",
                "timestamp": "2026-10-03T11:00:00Z",
                "currentBalanceUsd": "2476.12",
                "totalPnlUsd": "176.54",
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            report_input = load_report_input(path)

        self.assertEqual(report_input.capital_points[0].total_pnl_usd, Decimal("176.54"))

    def test_daily_pnl_uses_pre_window_baseline_and_last_daily_point(self) -> None:
        start = datetime(2026, 10, 1, tzinfo=UTC)
        end = datetime(2026, 10, 2, tzinfo=UTC)
        positions = (
            PositionInput("a", 999, "nest", "nft", SICKLE, active_from=start),
            PositionInput("b", 999, "nest", "nft", SICKLE, active_from=start),
        )
        points = (
            CapitalPoint("a", datetime(2026, 9, 30, 23, tzinfo=UTC), Decimal("100"), Decimal("10")),
            CapitalPoint("b", datetime(2026, 9, 30, 23, tzinfo=UTC), Decimal("50"), Decimal("5")),
            CapitalPoint("a", datetime(2026, 10, 1, 12, tzinfo=UTC), Decimal("110"), Decimal("24")),
            CapitalPoint("b", datetime(2026, 10, 1, 18, tzinfo=UTC), Decimal("55"), Decimal("11")),
        )

        day = aggregate_daily_capital(positions, points, start, end)[start.date()]

        self.assertEqual(day.cumulative_pnl_usd, Decimal("35"))
        self.assertEqual(day.daily_pnl_usd, Decimal("20"))
        self.assertFalse(day.pnl_is_estimated)

    def test_new_position_estimates_pnl_and_value_without_daily_gaps(self) -> None:
        start = datetime(2026, 10, 1, tzinfo=UTC)
        end = datetime(2026, 10, 3, tzinfo=UTC)
        opened = datetime(2026, 10, 1, 20, tzinfo=UTC)
        positions = (
            PositionInput("new", 999, "nest", "nft", SICKLE, active_from=opened),
        )
        points = (
            CapitalPoint(
                "new",
                datetime(2026, 10, 2, 4, tzinfo=UTC),
                Decimal("100"),
                Decimal("8"),
            ),
            CapitalPoint(
                "new",
                datetime(2026, 10, 2, 23, tzinfo=UTC),
                Decimal("110"),
                Decimal("10"),
            ),
        )

        days = aggregate_daily_capital(positions, points, start, end)
        first = days[start.date()]
        second = days[datetime(2026, 10, 2, tzinfo=UTC).date()]

        self.assertEqual(first.cumulative_pnl_usd, Decimal("4"))
        self.assertEqual(first.daily_pnl_usd, Decimal("4"))
        self.assertTrue(first.pnl_is_estimated)
        self.assertTrue(first.cumulative_pnl_is_estimated)
        self.assertTrue(first.daily_pnl_is_estimated)
        self.assertEqual(first.position_value_usd, Decimal("100"))
        self.assertEqual(first.daily_position_value_change_usd, Decimal("100"))
        self.assertTrue(first.position_value_is_estimated)
        self.assertTrue(first.daily_position_value_change_is_estimated)

        self.assertEqual(second.cumulative_pnl_usd, Decimal("10"))
        self.assertEqual(second.daily_pnl_usd, Decimal("6"))
        self.assertTrue(second.pnl_is_estimated)
        self.assertFalse(second.cumulative_pnl_is_estimated)
        self.assertTrue(second.daily_pnl_is_estimated)
        self.assertEqual(second.position_value_usd, Decimal("110"))
        self.assertEqual(second.daily_position_value_change_usd, Decimal("10"))
        self.assertFalse(second.position_value_is_estimated)
        self.assertTrue(second.daily_position_value_change_is_estimated)


if __name__ == "__main__":
    unittest.main()
