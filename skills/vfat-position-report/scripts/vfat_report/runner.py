from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .aggregate import build_report
from .cache import ReportCache
from .capital import aggregate_daily_capital
from .contracts import Diagnostics, PositionInput, load_report_input, write_report_json
from .events import ChainProfile, decode_receipt, load_chain_profile, merge_position_activity
from .html_report import render_html
from .rpc import JsonRpcClient


DEFAULT_RPCS = ("https://rpc.hyperliquid.xyz/evm", "https://rpc.hypurrscan.io")


def run(arguments: Namespace) -> int:
    explicit_now = _parse_now(arguments.now) if arguments.now else None
    report_input = load_report_input(Path(arguments.input), now=explicit_now)
    skill_root = Path(__file__).resolve().parents[2]
    profile = load_chain_profile(skill_root / "profiles" / "hyperevm-nest.json")
    profile = profile_for_positions(profile, report_input.positions)
    cache = ReportCache(Path(arguments.cache_dir), profile.chain_id, report_input.wallet)
    activities = merge_position_activity(report_input.activities)
    transactions = []
    warnings: list[str] = []
    rpc_endpoints = tuple(arguments.rpc) or DEFAULT_RPCS
    client = JsonRpcClient(rpc_endpoints) if activities else None
    for activity in activities:
        if arguments.refresh or cache.receipt_needs_fetch(activity.transaction_hash):
            receipt = client.get_receipt(activity.transaction_hash) if client else None
            cache.put_receipt(activity.transaction_hash, receipt)
        receipt = cache.get_receipt(activity.transaction_hash)
        if receipt is None:
            warnings.append(f"receipt_unavailable:{activity.transaction_hash}")
            continue
        transactions.append(decode_receipt(activity, receipt, profile))

    capital = aggregate_daily_capital(
        report_input.positions,
        report_input.capital_points,
        report_input.start,
        report_input.end,
    )
    diagnostics = Diagnostics(
        warnings=tuple(warnings + cache.diagnostics),
        reasons=(),
        rpc_endpoints=rpc_endpoints if activities else (),
    )
    report = build_report(report_input, transactions, capital, diagnostics)
    output = Path(arguments.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_report_json(report, output / "report.json")
    (output / "report.html").write_text(
        render_html(report), encoding="utf-8", newline="\n"
    )
    return 0


def profile_for_positions(
    profile: ChainProfile, positions: Iterable[PositionInput]
) -> ChainProfile:
    tracked = frozenset(
        position.sickle_address.lower()
        for position in positions
        if position.chain_id == profile.chain_id
    )
    return replace(profile, tracked_sickle_addresses=tracked)


def _parse_now(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)
