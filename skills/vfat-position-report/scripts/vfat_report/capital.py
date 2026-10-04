from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
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
        result[cursor.date()] = _aggregate_interval(
            selected,
            points_by_position,
            point_times,
            interval_start,
            interval_end,
            minimum_coverage,
            is_full_day=interval_start == cursor and interval_end == next_day,
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
