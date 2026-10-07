from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Mapping

from .contracts import CapitalPoint, PositionInput


@dataclass(frozen=True)
class DailyCapital:
    average_usd: Decimal | None
    coverage_ratio: Decimal
    status: str
    reasons: tuple[str, ...] = ()
    cumulative_pnl_usd: Decimal | None = None
    daily_pnl_usd: Decimal | None = None
    position_value_usd: Decimal | None = None
    daily_position_value_change_usd: Decimal | None = None
    pnl_is_estimated: bool = False
    cumulative_pnl_is_estimated: bool = False
    daily_pnl_is_estimated: bool = False
    position_value_is_estimated: bool = False
    daily_position_value_change_is_estimated: bool = False


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


def aggregate_daily_capital(
    positions: Iterable[PositionInput],
    capital_points: Iterable[CapitalPoint],
    start: datetime,
    end: datetime,
    minimum_coverage: Decimal = Decimal("0.75"),
) -> Mapping[date, DailyCapital]:
    start = _utc(start, "start")
    end = _utc(end, "end")
    if start >= end:
        raise ValueError("start must be earlier than end")

    selected = tuple(positions)
    points_by_position: dict[str, list[CapitalPoint]] = {
        item.position_id: [] for item in selected
    }
    for point in capital_points:
        if point.position_id in points_by_position:
            points_by_position[point.position_id].append(point)
    point_times: dict[str, list[datetime]] = {}
    for position_id, points in points_by_position.items():
        points.sort(key=lambda item: item.timestamp)
        point_times[position_id] = [_utc(item.timestamp, "capital point timestamp") for item in points]

    result: dict[date, DailyCapital] = {}
    cursor = datetime.combine(start.date(), time.min, tzinfo=timezone.utc)
    while cursor < end:
        next_day = cursor + timedelta(days=1)
        interval_start = max(start, cursor)
        interval_end = min(end, next_day)
        daily = _aggregate_interval(
            selected,
            points_by_position,
            point_times,
            interval_start,
            interval_end,
            minimum_coverage,
            is_full_day=interval_start == cursor and interval_end == next_day,
        )
        opening_pnl, opening_pnl_estimated = _portfolio_pnl_at(
            selected, points_by_position, point_times, interval_start
        )
        closing_pnl, closing_pnl_estimated = _portfolio_pnl_at(
            selected, points_by_position, point_times, interval_end
        )
        opening_value, opening_value_estimated = _portfolio_value_at(
            selected, points_by_position, point_times, interval_start
        )
        closing_value, closing_value_estimated = _portfolio_value_at(
            selected, points_by_position, point_times, interval_end
        )
        daily_pnl = (
            closing_pnl - opening_pnl
            if closing_pnl is not None and opening_pnl is not None
            else None
        )
        daily_value_change = (
            closing_value - opening_value
            if closing_value is not None and opening_value is not None
            else None
        )
        result[cursor.date()] = replace(
            daily,
            cumulative_pnl_usd=closing_pnl,
            daily_pnl_usd=daily_pnl,
            position_value_usd=closing_value,
            daily_position_value_change_usd=daily_value_change,
            pnl_is_estimated=(
                closing_pnl_estimated
                or (daily_pnl is not None and opening_pnl_estimated)
            ),
            cumulative_pnl_is_estimated=closing_pnl_estimated,
            daily_pnl_is_estimated=(
                closing_pnl_estimated
                or (daily_pnl is not None and opening_pnl_estimated)
            ),
            position_value_is_estimated=closing_value_estimated,
            daily_position_value_change_is_estimated=(
                closing_value_estimated
                or (daily_value_change is not None and opening_value_estimated)
            ),
        )
        cursor = next_day
    return result


def _aggregate_interval(
    positions: tuple[PositionInput, ...],
    points_by_position: Mapping[str, list[CapitalPoint]],
    point_times: Mapping[str, list[datetime]],
    interval_start: datetime,
    interval_end: datetime,
    minimum_coverage: Decimal,
    *,
    is_full_day: bool,
) -> DailyCapital:
    boundaries = {interval_start, interval_end}
    for position in positions:
        if position.active_from:
            active_from = _utc(position.active_from, "active_from")
            if interval_start < active_from < interval_end:
                boundaries.add(active_from)
        if position.active_to:
            active_to = _utc(position.active_to, "active_to")
            if interval_start < active_to < interval_end:
                boundaries.add(active_to)
        for timestamp in point_times[position.position_id]:
            if interval_start < timestamp < interval_end:
                boundaries.add(timestamp)

    ordered = sorted(boundaries)
    covered_seconds = Decimal(0)
    value_seconds = Decimal(0)
    uncovered_segments = 0

    for segment_start, segment_end in zip(ordered, ordered[1:]):
        duration = Decimal(str((segment_end - segment_start).total_seconds()))
        active = [
            position
            for position in positions
            if _is_active(position, segment_start)
        ]
        if not active:
            covered_seconds += duration
            continue

        values: list[Decimal] = []
        for position in active:
            timestamps = point_times[position.position_id]
            index = bisect_right(timestamps, segment_start) - 1
            if index < 0:
                break
            point = points_by_position[position.position_id][index]
            if position.active_from and point.timestamp < position.active_from:
                break
            values.append(point.current_balance_usd)
        if len(values) != len(active):
            uncovered_segments += 1
            continue

        covered_seconds += duration
        value_seconds += sum(values, Decimal(0)) * duration

    total_seconds = Decimal(str((interval_end - interval_start).total_seconds()))
    coverage = covered_seconds / total_seconds if total_seconds else Decimal(0)
    reasons: list[str] = []
    if uncovered_segments:
        reasons.append("capital_history_gap")
    if coverage < minimum_coverage:
        reasons.append("coverage_below_75_percent")
        average = None
        status = "unreliable"
    else:
        average = value_seconds / covered_seconds if covered_seconds else Decimal(0)
        status = "complete" if is_full_day and coverage == 1 else "partial"
    return DailyCapital(average, coverage, status, tuple(reasons))


def _is_active(position: PositionInput, timestamp: datetime) -> bool:
    if position.active_from and timestamp < _utc(position.active_from, "active_from"):
        return False
    if position.active_to and timestamp >= _utc(position.active_to, "active_to"):
        return False
    return True


def _portfolio_pnl_at(
    positions: tuple[PositionInput, ...],
    points_by_position: Mapping[str, list[CapitalPoint]],
    point_times: Mapping[str, list[datetime]],
    timestamp: datetime,
) -> tuple[Decimal | None, bool]:
    values: list[Decimal] = []
    estimated = False
    for position in positions:
        if position.active_from and timestamp < _utc(position.active_from, "active_from"):
            continue
        timestamps = point_times[position.position_id]
        index = bisect_right(timestamps, timestamp) - 1
        if index < 0:
            if not position.active_from or not timestamps:
                return None, False
            active_from = _utc(position.active_from, "active_from")
            first_timestamp = timestamps[0]
            first_value = points_by_position[position.position_id][0].total_pnl_usd
            if first_value is None or timestamp < active_from or first_timestamp <= active_from:
                return None, False
            elapsed = Decimal(str((timestamp - active_from).total_seconds()))
            duration = Decimal(str((first_timestamp - active_from).total_seconds()))
            values.append(first_value * elapsed / duration)
            estimated = True
            continue
        value = points_by_position[position.position_id][index].total_pnl_usd
        if value is None:
            return None, False
        values.append(value)
    return sum(values, Decimal(0)), estimated


def _portfolio_value_at(
    positions: tuple[PositionInput, ...],
    points_by_position: Mapping[str, list[CapitalPoint]],
    point_times: Mapping[str, list[datetime]],
    timestamp: datetime,
) -> tuple[Decimal | None, bool]:
    values: list[Decimal] = []
    estimated = False
    for position in positions:
        if not _is_active(position, timestamp):
            continue
        timestamps = point_times[position.position_id]
        index = bisect_right(timestamps, timestamp) - 1
        active_from = (
            _utc(position.active_from, "active_from")
            if position.active_from
            else None
        )
        if index >= 0:
            point = points_by_position[position.position_id][index]
            if not active_from or _utc(point.timestamp, "capital point timestamp") >= active_from:
                values.append(point.current_balance_usd)
                continue
        first_valid = next(
            (
                point
                for point in points_by_position[position.position_id]
                if not active_from
                or _utc(point.timestamp, "capital point timestamp") >= active_from
            ),
            None,
        )
        if first_valid is None:
            return None, False
        values.append(first_valid.current_balance_usd)
        estimated = True
    return sum(values, Decimal(0)), estimated
