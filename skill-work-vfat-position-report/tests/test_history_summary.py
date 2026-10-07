from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from vfat_report.aggregate import build_report
from vfat_report.contracts import CapitalPoint, Diagnostics, ReportInput


UTC = timezone.utc


class HistorySummaryTests(unittest.TestCase):
    def test_input_summary_reports_value_and_pnl_history_ranges(self) -> None:
        report_input = ReportInput(
            schema_version="1.0",
            wallet="0x330d2a845d2df4e329034d72719c7c53f9c1f87a",
            start=datetime(2026, 9, 20, tzinfo=UTC),
            end=datetime(2026, 9, 22, tzinfo=UTC),
            chain_ids=(999,),
            protocols=("nest",),
            reward_tokens=(),
            positions=(),
            activities=(),
            capital_points=(
                CapitalPoint(
                    "manager:1",
                    datetime(2026, 9, 20, tzinfo=UTC),
                    Decimal("100"),
                    None,
                ),
                CapitalPoint(
                    "manager:1",
                    datetime(2026, 9, 21, tzinfo=UTC),
                    Decimal("110"),
                    Decimal("10"),
                ),
            ),
            source={"provider": "vfat-mcp"},
        )

        report = build_report(
            report_input,
            transactions=(),
            capital={},
            diagnostics=Diagnostics((), (), ()),
        )

        self.assertEqual(
            report.input_summary["historyFrom"],
            datetime(2026, 9, 20, tzinfo=UTC),
        )
        self.assertEqual(
            report.input_summary["historyTo"],
            datetime(2026, 9, 21, tzinfo=UTC),
        )
        self.assertEqual(
            report.input_summary["pnlFrom"],
            datetime(2026, 9, 21, tzinfo=UTC),
        )
        self.assertEqual(
            report.input_summary["pnlTo"],
            datetime(2026, 9, 21, tzinfo=UTC),
        )


if __name__ == "__main__":
    unittest.main()
