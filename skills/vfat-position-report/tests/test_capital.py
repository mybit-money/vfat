from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from vfat_report.capital import aggregate_daily_capital
from vfat_report.contracts import CapitalPoint, PositionInput


UTC = timezone.utc


def instant(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 1, hour, minute, tzinfo=UTC)


def position(
    position_id: str,
    *,
    active_from: datetime | None = None,
    active_to: datetime | None = None,
) -> PositionInput:
    return PositionInput(
        position_id=position_id,
        chain_id=999,
        protocol="nest",
        position_type="nft",
        sickle_address="0x05a34ca31a38c136b8489d4147112cfc4a92a155",
        active_from=active_from or instant(0),
        active_to=active_to,
    )


class CapitalTests(unittest.TestCase):
    def test_time_weighted_capital_carries_last_observation(self) -> None:
        positions = (position("a"), position("b"))
        points = (
            CapitalPoint("a", instant(0), Decimal("100")),
            CapitalPoint("a", instant(12), Decimal("200")),
            CapitalPoint("b", instant(0), Decimal("50")),
        )

        result = aggregate_daily_capital(positions, points, instant(0), instant(0).replace(day=2))

        day = result[instant(0).date()]
        self.assertEqual(day.average_usd, Decimal("200"))
        self.assertEqual(day.coverage_ratio, Decimal("1"))
        self.assertEqual(day.status, "complete")

    def test_time_weighted_capital_reports_gap_and_threshold(self) -> None:
        positions = (position("a"),)
        end = instant(0).replace(day=2)

        usable = aggregate_daily_capital(
            positions,
            (CapitalPoint("a", instant(6), Decimal("100")),),
            instant(0),
            end,
        )[instant(0).date()]
        unreliable = aggregate_daily_capital(
            positions,
            (CapitalPoint("a", instant(6, 14), Decimal("100")),),
            instant(0),
            end,
        )[instant(0).date()]

        self.assertEqual(usable.coverage_ratio, Decimal("0.75"))
        self.assertEqual(usable.average_usd, Decimal("100"))
        self.assertEqual(unreliable.coverage_ratio.quantize(Decimal("0.01")), Decimal("0.74"))
        self.assertIsNone(unreliable.average_usd)
        self.assertIn("coverage_below_75_percent", unreliable.reasons)

    def test_closed_position_contributes_only_while_active(self) -> None:
        positions = (
            position("closed", active_to=instant(12)),
            position("open"),
        )
        points = (
            CapitalPoint("closed", instant(0), Decimal("100")),
            CapitalPoint("open", instant(0), Decimal("50")),
        )

        day = aggregate_daily_capital(
            positions, points, instant(0), instant(0).replace(day=2)
        )[instant(0).date()]

        self.assertEqual(day.average_usd, Decimal("100"))
        self.assertEqual(day.coverage_ratio, Decimal("1"))

    def test_partial_first_day_is_kept_with_null_value(self) -> None:
        positions = (position("a"),)
        points = (CapitalPoint("a", instant(12), Decimal("100")),)

        result = aggregate_daily_capital(
            positions, points, instant(0), instant(0).replace(day=2)
        )

        self.assertIn(instant(0).date(), result)
        self.assertIsNone(result[instant(0).date()].average_usd)
        self.assertEqual(result[instant(0).date()].status, "unreliable")


if __name__ == "__main__":
    unittest.main()
