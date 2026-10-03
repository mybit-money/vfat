from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from vfat_report.aggregate import build_daily_aggregates
from vfat_report.capital import DailyCapital
from vfat_report.contracts import NormalizedTransaction, TokenAmount, Valuation


UTC = timezone.utc
TOKEN = "0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035"


def transaction(
    tx_hash: str,
    timestamp: datetime,
    *,
    gross_usd: Decimal | None = Decimal("120"),
    net_usd: Decimal | None = Decimal("100"),
    gas_usd: Decimal | None = Decimal("10"),
    raw_claim: int = 1_000_000_000_000_000_000,
) -> NormalizedTransaction:
    return NormalizedTransaction(
        chain_id=999,
        transaction_hash=tx_hash,
        timestamp=timestamp,
        action_type="compounded",
        source_position_ids=("nft:1", "nft:2"),
        recipient_position_ids=("nft:3",),
        automation_payment_method="gas-account",
        gross_claims=(TokenAmount(TOKEN, "NEST", 18, raw_claim),),
        gross_claim_usd=Valuation(gross_usd, source="fixture" if gross_usd is not None else None, reason="missing" if gross_usd is None else None),
        net_compound_usd=Valuation(net_usd, source="fixture" if net_usd is not None else None, reason="missing" if net_usd is None else None),
        gas_account_debit_usd=Valuation(gas_usd, source="fixture" if gas_usd is not None else None, reason="missing" if gas_usd is None else None),
    )


def capital(day: date, value: str = "1000") -> dict[date, DailyCapital]:
    return {day: DailyCapital(Decimal(value), Decimal("1"), "complete")}


class AggregateTests(unittest.TestCase):
    def test_aggregate_counts_unique_transactions_not_sources(self) -> None:
        day = date(2026, 10, 1)
        tx = transaction("0x" + "11" * 32, datetime(2026, 10, 1, 12, tzinfo=UTC))

        rows = build_daily_aggregates(
            (tx, tx), capital(day), datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC)
        )

        self.assertEqual(rows[0].claim_transaction_count, 1)
        self.assertEqual(rows[0].reward_amounts[0].raw_amount, 1_000_000_000_000_000_000)

    def test_completed_day_apr_uses_net_lp_minus_confirmed_gas_debit(self) -> None:
        day = date(2026, 10, 1)
        tx = transaction("0x" + "22" * 32, datetime(2026, 10, 1, 12, tzinfo=UTC))

        row = build_daily_aggregates(
            (tx,), capital(day), datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC)
        )[0]

        self.assertEqual(row.net_compound_usd, Decimal("100"))
        self.assertEqual(row.gas_account_debit_usd, Decimal("10"))
        self.assertEqual(row.realized_apr_percent, Decimal("3285"))

    def test_current_day_apr_is_prorated_by_elapsed_utc_fraction(self) -> None:
        day = date(2026, 10, 3)
        now = datetime(2026, 10, 3, 12, tzinfo=UTC)
        tx = transaction(
            "0x" + "33" * 32,
            datetime(2026, 10, 3, 6, tzinfo=UTC),
            gross_usd=Decimal("12"),
            net_usd=Decimal("10"),
            gas_usd=Decimal("0"),
        )

        row = build_daily_aggregates(
            (tx,), capital(day), datetime(2026, 10, 3, tzinfo=UTC), now, now
        )[0]

        self.assertEqual(row.realized_apr_percent, Decimal("730"))
        self.assertEqual(row.status, "partial")

    def test_partial_first_day_apr_is_prorated_by_elapsed_utc_fraction(self) -> None:
        tx = transaction(
            "0x" + "77" * 32,
            datetime(2026, 10, 1, 18, tzinfo=UTC),
            net_usd=Decimal("10"),
            gas_usd=Decimal("0"),
        )

        row = build_daily_aggregates(
            (tx,), capital(date(2026, 10, 1)), datetime(2026, 10, 1, 12, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC)
        )[0]

        self.assertEqual(row.realized_apr_percent, Decimal("730"))

    def test_zero_activity_day_is_retained(self) -> None:
        start = datetime(2026, 10, 1, tzinfo=UTC)
        end = datetime(2026, 10, 3, tzinfo=UTC)
        capitals = {
            date(2026, 10, 1): DailyCapital(Decimal("1000"), Decimal("1"), "complete"),
            date(2026, 10, 2): DailyCapital(Decimal("1000"), Decimal("1"), "complete"),
        }

        rows = build_daily_aggregates((), capitals, start, end, end)

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.claim_transaction_count == 0 for row in rows))
        self.assertTrue(all(row.realized_apr_percent == 0 for row in rows))

    def test_daily_aggregate_propagates_missing_usd(self) -> None:
        day = date(2026, 10, 1)
        tx = transaction(
            "0x" + "44" * 32,
            datetime(2026, 10, 1, 12, tzinfo=UTC),
            net_usd=None,
        )

        row = build_daily_aggregates(
            (tx,), capital(day), datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC)
        )[0]

        self.assertIsNone(row.net_compound_usd)
        self.assertIsNone(row.realized_apr_percent)
        self.assertIn("net_compound_usd_unavailable", row.reasons)

    def test_rows_are_newest_first(self) -> None:
        start = datetime(2026, 10, 1, tzinfo=UTC)
        end = datetime(2026, 10, 3, tzinfo=UTC)
        capitals = {
            date(2026, 10, 1): DailyCapital(Decimal("1000"), Decimal("1"), "complete"),
            date(2026, 10, 2): DailyCapital(Decimal("1000"), Decimal("1"), "complete"),
        }

        rows = build_daily_aggregates((), capitals, start, end, end)

        self.assertEqual([row.day for row in rows], [date(2026, 10, 2), date(2026, 10, 1)])


if __name__ == "__main__":
    unittest.main()
