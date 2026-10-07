from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from vfat_report.aggregate import build_daily_aggregates
from vfat_report.capital import DailyCapital
from vfat_report.contracts import NormalizedTransaction, Valuation


UTC = timezone.utc


class PortfolioMetricTests(unittest.TestCase):
    def test_net_claim_deducts_fee_and_confirmed_gas_account_debit(self) -> None:
        day = date(2026, 10, 1)
        transaction = NormalizedTransaction(
            chain_id=999,
            transaction_hash="0x" + "ab" * 32,
            timestamp=datetime(2026, 10, 1, 12, tzinfo=UTC),
            action_type="compound",
            gross_claim_usd=Valuation(Decimal("100"), source="test"),
            automation_fee_usd=Valuation(Decimal("1.8"), source="test"),
            net_compound_usd=Valuation(Decimal("97"), source="test"),
            gas_account_debit_usd=Valuation(Decimal("0.2"), source="test"),
        )
        capital = {
            day: DailyCapital(
                Decimal("1000"),
                Decimal("1"),
                "complete",
                position_value_usd=Decimal("1100"),
                daily_position_value_change_usd=Decimal("100"),
            )
        }

        rows = build_daily_aggregates(
            [transaction],
            capital,
            datetime(2026, 10, 1, tzinfo=UTC),
            datetime(2026, 10, 2, tzinfo=UTC),
            datetime(2026, 10, 2, tzinfo=UTC),
        )

        self.assertEqual(rows[0].net_claim_usd, Decimal("98.0"))
        self.assertEqual(rows[0].position_value_usd, Decimal("1100"))
        self.assertEqual(rows[0].daily_position_value_change_usd, Decimal("100"))


if __name__ == "__main__":
    unittest.main()
