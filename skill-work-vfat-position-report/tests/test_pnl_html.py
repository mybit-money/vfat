from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from vfat_report.contracts import DailyAggregate, Diagnostics, Report
from vfat_report.html_report import render_html


class PnlHtmlTests(unittest.TestCase):
    def test_renders_labeled_axes_bars_toggles_and_completed_day_averages(self) -> None:
        report = Report(
            schema_version="1.0",
            generated_at=datetime(2026, 10, 3, 12, tzinfo=timezone.utc),
            input_summary={},
            days=(
                DailyAggregate(
                    day=date(2026, 10, 3), status="partial",
                    average_capital_usd=Decimal("2000"), capital_coverage=Decimal("1"),
                    gross_claim_usd=Decimal("25"), net_compound_usd=Decimal("20"),
                    automation_fee_usd=Decimal("0.45"), gas_account_debit_usd=Decimal("0.10"),
                    realized_apr_percent=Decimal("726.35"), claim_transaction_count=2,
                    cumulative_pnl_usd=Decimal("125"), daily_pnl_usd=Decimal("20"),
                    position_value_usd=Decimal("2200"),
                    daily_position_value_change_usd=Decimal("300"),
                    net_claim_usd=Decimal("24.45"),
                    pnl_is_estimated=True,
                    cumulative_pnl_is_estimated=False,
                    daily_pnl_is_estimated=True,
                    position_value_is_estimated=False,
                    daily_position_value_change_is_estimated=True,
                ),
                DailyAggregate(
                    day=date(2026, 10, 2), status="complete",
                    average_capital_usd=Decimal("1900"), capital_coverage=Decimal("1"),
                    gross_claim_usd=Decimal("0"), net_compound_usd=Decimal("0"),
                    automation_fee_usd=Decimal("0"), gas_account_debit_usd=Decimal("0"),
                    realized_apr_percent=Decimal("-5"), claim_transaction_count=0,
                    cumulative_pnl_usd=Decimal("105"), daily_pnl_usd=Decimal("-5"),
                    position_value_usd=Decimal("1900"),
                    daily_position_value_change_usd=Decimal("-50"),
                    net_claim_usd=Decimal("0"),
                ),
            ),
            transactions=(),
            diagnostics=Diagnostics((), (), ()),
        )

        rendered = render_html(report)

        self.assertIn('data-chart="capital-apr"', rendered)
        self.assertIn('data-chart="pnl"', rendered)
        self.assertIn('data-chart="claims"', rendered)
        self.assertIn('data-axis="date"', rendered)
        self.assertIn('data-axis="cumulative-pnl"', rendered)
        self.assertIn('data-axis="daily-pnl"', rendered)
        self.assertIn('class="bar negative"', rendered)
        self.assertIn('data-average="capital"', rendered)
        self.assertIn('data-average="apr"', rendered)
        self.assertIn('data-average="cumulative-pnl"', rendered)
        self.assertIn('data-average="daily-pnl"', rendered)
        self.assertIn('data-average="position-change"', rendered)
        self.assertIn('data-average="net-claim"', rendered)
        self.assertIn('id="toggle-cumulative-pnl"', rendered)
        self.assertIn('id="toggle-daily-pnl"', rendered)
        self.assertIn('id="toggle-position-change"', rendered)
        self.assertIn('id="toggle-net-claim"', rendered)
        self.assertIn('data-estimated="true"', rendered)
        self.assertIn("оценка", rendered)
        self.assertIn("<td>2200.00</td><td>≈ 300.00</td>", rendered)
        self.assertIn("<td>125.00</td><td>≈ 20.00</td>", rendered)
        self.assertNotIn("http://", rendered)
        self.assertNotIn("https://", rendered)


if __name__ == "__main__":
    unittest.main()
