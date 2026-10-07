from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from tests.test_aggregate import TOKEN, capital, transaction
from vfat_report.aggregate import build_daily_aggregates
from vfat_report.contracts import TokenAmount, Valuation


class NonClaimFeeAggregationTests(unittest.TestCase):
    def test_increase_with_fee_transfer_is_not_compound_income(self) -> None:
        day = date(2026, 10, 1)
        increased = replace(
            transaction(
                "0x" + "66" * 32,
                datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
            ),
            action_type="increased",
            automation_fees=(TokenAmount(TOKEN, "NEST", 18, 2 * 10**18),),
            automation_fee_usd=Valuation(Decimal("0.04"), source="fixture"),
            net_compound_usd=Valuation(Decimal("900"), source="fixture"),
        )

        row = build_daily_aggregates(
            (increased,),
            capital(day),
            datetime(2026, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 10, 2, tzinfo=timezone.utc),
            datetime(2026, 10, 3, tzinfo=timezone.utc),
        )[0]

        self.assertEqual(row.claim_transaction_count, 0)
        self.assertEqual(row.net_compound_usd, Decimal(0))
        self.assertEqual(row.automation_fee_usd, Decimal(0))
        self.assertEqual(row.realized_apr_percent, Decimal(0))


if __name__ == "__main__":
    unittest.main()
