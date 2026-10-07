from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from tests.test_aggregate import capital, transaction
from vfat_report.aggregate import build_daily_aggregates
from vfat_report.contracts import Valuation


class NonClaimAggregationTests(unittest.TestCase):
    def test_increase_activity_does_not_count_as_claim_or_change_daily_values(self) -> None:
        day = date(2026, 10, 1)
        increased = replace(
            transaction(
                "0x" + "55" * 32,
                datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
            ),
            action_type="increased",
            gross_claims=(),
            gross_claim_usd=Valuation(None, reason="historical_reward_usd_unavailable"),
            net_compound_usd=Valuation(None, reason="historical_lp_usd_unavailable"),
        )

        row = build_daily_aggregates(
            (increased,),
            capital(day),
            datetime(2026, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 10, 2, tzinfo=timezone.utc),
            datetime(2026, 10, 3, tzinfo=timezone.utc),
        )[0]

        self.assertEqual(row.claim_transaction_count, 0)
        self.assertEqual(row.gross_claim_usd, Decimal(0))
        self.assertEqual(row.net_compound_usd, Decimal(0))
        self.assertEqual(row.realized_apr_percent, Decimal(0))
        self.assertEqual(row.reasons, ())


if __name__ == "__main__":
    unittest.main()
