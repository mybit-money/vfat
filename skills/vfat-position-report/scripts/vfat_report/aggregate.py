from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Mapping

from .capital import DailyCapital
from .contracts import (
    DailyAggregate,
    Diagnostics,
    NormalizedTransaction,
    Report,
    ReportInput,
    TokenAmount,
    Valuation,
)


SECONDS_PER_DAY = Decimal(86_400)
CLAIM_ACTIONS = frozenset(
    {"claim", "claimed", "compound", "compounded", "harvest", "harvested"}
)


def build_daily_aggregates(
    transactions: Iterable[NormalizedTransaction],
    capital: Mapping[date, DailyCapital],
    start: datetime,
    end: datetime,
    now: datetime,
) -> list[DailyAggregate]:
    start = _utc(start)
    end = _utc(end)
    now = _utc(now)
    if start >= end:
        raise ValueError("start must be earlier than end")

    unique: dict[tuple[int, str], NormalizedTransaction] = {}
    for transaction in transactions:
        timestamp = _utc(transaction.timestamp)
        if start <= timestamp < end and _is_claim_transaction(transaction):
            unique.setdefault(
                (transaction.chain_id, transaction.transaction_hash.lower()), transaction
            )

    by_day: dict[date, list[NormalizedTransaction]] = {}
    for transaction in unique.values():
        by_day.setdefault(_utc(transaction.timestamp).date(), []).append(transaction)

    rows: list[DailyAggregate] = []
    cursor = datetime.combine(start.date(), time.min, tzinfo=timezone.utc)
    while cursor < end:
        day = cursor.date()
        day_transactions = by_day.get(day, [])
        daily_capital = capital.get(
            day,
            DailyCapital(None, Decimal(0), "unreliable", ("capital_unavailable",)),
        )
        rows.append(
            _aggregate_day(day, day_transactions, daily_capital, start, end, now)
        )
        cursor += timedelta(days=1)
    rows.sort(key=lambda row: row.day, reverse=True)
    return rows


def _is_claim_transaction(transaction: NormalizedTransaction) -> bool:
    action = transaction.action_type.strip().lower().replace("-", "_")
    return bool(
        transaction.gross_claims
        or transaction.automation_fees
        or action in CLAIM_ACTIONS
    )


def build_report(
    report_input: ReportInput,
    transactions: Iterable[NormalizedTransaction],
    capital: Mapping[date, DailyCapital],
    diagnostics: Diagnostics,
) -> Report:
    transaction_tuple = tuple(transactions)
    rows = build_daily_aggregates(
        transaction_tuple,
        capital,
        report_input.start,
        report_input.end,
        report_input.end,
    )
    return Report(
        schema_version="1.0",
        generated_at=report_input.end,
        input_summary={
            "wallet": report_input.wallet,
            "chainIds": list(report_input.chain_ids),
            "protocols": list(report_input.protocols),
            "from": report_input.start,
            "to": report_input.end,
        },
        days=tuple(rows),
        transactions=transaction_tuple,
        diagnostics=diagnostics,
    )


def _aggregate_day(
    day: date,
    transactions: list[NormalizedTransaction],
    daily_capital: DailyCapital,
    report_start: datetime,
    report_end: datetime,
    now: datetime,
) -> DailyAggregate:
    reasons = list(daily_capital.reasons)
    gross_usd = _sum_valuations(
        [item.gross_claim_usd for item in transactions],
        "gross_claim_usd_unavailable",
        reasons,
    )
    net_usd = _sum_valuations(
        [item.net_compound_usd for item in transactions],
        "net_compound_usd_unavailable",
        reasons,
    )
    gas_usd = _sum_valuations(
        [item.gas_account_debit_usd for item in transactions],
        "gas_account_debit_usd_unavailable",
        reasons,
    )
    fee_valuations: list[Valuation] = []
    for item in transactions:
        valuation = getattr(item, "automation_fee_usd", None)
        if valuation is not None:
            fee_valuations.append(valuation)
        elif item.automation_fees:
            fee_valuations.append(Valuation(None, reason="automation_fee_usd_unavailable"))
        else:
            fee_valuations.append(Valuation(Decimal(0), source="none"))
    fee_usd = _sum_valuations(
        fee_valuations,
        "automation_fee_usd_unavailable",
        reasons,
    )

    apr: Decimal | None = None
    if daily_capital.average_usd is None:
        _add_reason(reasons, "capital_unavailable")
    elif daily_capital.average_usd <= 0:
        _add_reason(reasons, "capital_not_positive")
    elif net_usd is not None and gas_usd is not None:
        economic_net = net_usd - gas_usd
        factor = Decimal(365) * Decimal(100)
        if day == now.date():
            day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
            elapsed_end = min(report_end, now, day_start + timedelta(days=1))
            elapsed_start = max(report_start, day_start)
            elapsed_fraction = Decimal(
                str((elapsed_end - elapsed_start).total_seconds())
            ) / SECONDS_PER_DAY
            if elapsed_fraction > 0:
                factor /= elapsed_fraction
            else:
                _add_reason(reasons, "current_day_has_no_elapsed_time")
                factor = Decimal(0)
        if factor:
            apr = economic_net / daily_capital.average_usd * factor

    status = daily_capital.status
    if status != "unreliable":
        day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        if day_start < report_start or day_start + timedelta(days=1) > report_end or day == now.date():
            status = "partial"
    return DailyAggregate(
        day=day,
        status=status,
        average_capital_usd=daily_capital.average_usd,
        capital_coverage=daily_capital.coverage_ratio,
        gross_claim_usd=gross_usd,
        net_compound_usd=net_usd,
        automation_fee_usd=fee_usd,
        gas_account_debit_usd=gas_usd,
        realized_apr_percent=apr,
        claim_transaction_count=len(transactions),
        reward_amounts=_sum_token_amounts(transactions),
        reasons=tuple(reasons),
    )


def _sum_valuations(
    valuations: list[Valuation],
    missing_reason: str,
    reasons: list[str],
) -> Decimal | None:
    if not valuations:
        return Decimal(0)
    if any(item.usd is None for item in valuations):
        _add_reason(reasons, missing_reason)
        return None
    return sum((item.usd or Decimal(0) for item in valuations), Decimal(0))


def _sum_token_amounts(
    transactions: Iterable[NormalizedTransaction],
) -> tuple[TokenAmount, ...]:
    totals: dict[tuple[str, str | None, int], int] = {}
    for transaction in transactions:
        for amount in transaction.gross_claims:
            key = (amount.token_address.lower(), amount.symbol, amount.decimals)
            totals[key] = totals.get(key, 0) + amount.raw_amount
    return tuple(
        TokenAmount(address, symbol, decimals, raw)
        for (address, symbol, decimals), raw in sorted(totals.items())
    )


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(timezone.utc)
