from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from vfat_report.cli import main
from vfat_report.contracts import DailyAggregate, Diagnostics, Report, TokenAmount
from vfat_report.html_report import render_html


UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"


def sample_report() -> Report:
    return Report(
        schema_version="1.0",
        generated_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
        input_summary={"wallet": "0x330d2a845d2df4e329034d72719c7c53f9c1f87a"},
        days=(
            DailyAggregate(
                day=date(2026, 10, 3),
                status="partial",
                average_capital_usd=Decimal("2000"),
                capital_coverage=Decimal("1"),
                gross_claim_usd=Decimal("25"),
                net_compound_usd=Decimal("20"),
                automation_fee_usd=Decimal("0.45"),
                gas_account_debit_usd=Decimal("0.10"),
                realized_apr_percent=Decimal("726.35"),
                claim_transaction_count=2,
            ),
            DailyAggregate(
                day=date(2026, 10, 2),
                status="unreliable",
                average_capital_usd=None,
                capital_coverage=Decimal("0.5"),
                gross_claim_usd=Decimal("0"),
                net_compound_usd=Decimal("0"),
                automation_fee_usd=Decimal("0"),
                gas_account_debit_usd=Decimal("0"),
                realized_apr_percent=None,
                claim_transaction_count=0,
                reasons=("coverage_below_75_percent",),
            ),
        ),
        transactions=(),
        diagnostics=Diagnostics((), (), ()),
    )


class HtmlCliTests(unittest.TestCase):
    def test_html_is_self_contained_and_has_dual_axes(self) -> None:
        html = render_html(sample_report())

        self.assertIn("<svg", html)
        self.assertIn('data-axis="capital"', html)
        self.assertIn('data-axis="apr"', html)
        self.assertIn('id="toggle-capital"', html)
        self.assertIn('id="toggle-apr"', html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("<link", html)
        self.assertNotIn("<script src=", html)

    def test_unreliable_capital_serializes_as_chart_gap(self) -> None:
        html = render_html(sample_report())

        self.assertIn('"capital":null', html)
        self.assertIn('"apr":null', html)

    def test_current_day_is_marked_preliminary(self) -> None:
        html = render_html(sample_report())

        self.assertIn("предварительно", html)
        self.assertIn('stroke-dasharray="7 5"', html)
        self.assertIn('d="M888.00 32 V322"', html)

    def test_round_reward_amount_is_not_scientific(self) -> None:
        report = sample_report()
        nest = TokenAmount("0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035", "NEST", 18, 1000 * 10**18)
        today = replace(report.days[0], reward_amounts=(nest,))

        html = render_html(replace(report, days=(today, *report.days[1:])))

        self.assertIn("1000 NEST", html)

    def test_html_table_uses_required_column_order(self) -> None:
        html = render_html(sample_report())

        headers = [
            "Дата UTC",
            "Капитал, USD",
            "Собрано gross, USD",
            "APR net",
            "Net compound, USD",
            "VFAT fee, USD",
            "Gas account, USD",
            "Клеймов",
            "Награды в токенах",
            "Статус",
        ]
        positions = [html.index(f"<th>{header}</th>") for header in headers]
        self.assertEqual(positions, sorted(positions))

    def test_cli_writes_deterministic_json_and_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            common = [
                "--input",
                str(FIXTURES / "minimal-input.json"),
                "--cache-dir",
                str(root / "cache"),
                "--now",
                "2026-10-03T12:00:00Z",
            ]

            self.assertEqual(main([*common, "--output-dir", str(first)]), 0)
            self.assertEqual(main([*common, "--output-dir", str(second)]), 0)

            self.assertEqual((first / "report.json").read_bytes(), (second / "report.json").read_bytes())
            self.assertEqual((first / "report.html").read_bytes(), (second / "report.html").read_bytes())


if __name__ == "__main__":
    unittest.main()
