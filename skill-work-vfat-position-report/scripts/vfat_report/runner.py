from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .adapters.base import AdapterResolutionError, unavailable_transaction
from .adapters.registry import get_report_adapter, resolve_adapter_key
from .aggregate import CLAIM_ACTIONS, build_report
from .cache import ReportCache
from .capital import aggregate_daily_capital
from .contracts import Diagnostics, PositionInput, Report, load_report_input, write_report_json
from .events import (
    ChainProfile,
    merge_position_activity,
)
from .html_report import render_html
from .prices import DefiLlamaPriceClient, collect_price_requests, value_transaction
from .rpc import JsonRpcClient


DEFAULT_RPCS = ("https://rpc.hyperliquid.xyz/evm", "https://rpc.hypurrscan.io")


def run(arguments: Namespace) -> int:
    explicit_now = _parse_now(arguments.now) if arguments.now else None
    report_input = load_report_input(
        Path(arguments.input),
        now=explicit_now,
        history_root=arguments.history_root,
    )
    key = resolve_adapter_key(
        report_input.positions, report_input.protocols,
        getattr(arguments, "adapter", None),
    )
    adapter = get_report_adapter(key)
    if adapter is not None and not all(
        adapter.supports_position(position) for position in report_input.positions
    ):
        raise AdapterResolutionError("adapter_position_unsupported")
    activities = merge_position_activity(report_input.activities)
    if any(activity.chain_id != key.chain_id for activity in activities):
        raise AdapterResolutionError("activity_chain_mismatch")
    transactions = []
    warnings: list[str] = []
    priceable_indices: list[int] = []
    rpc_endpoints: tuple[str, ...] = ()
    cache = None
    if adapter is None:
        transactions = [
            unavailable_transaction(activity, "chain_protocol_unsupported")
            for activity in activities
        ]
    else:
        profile = adapter.profile_for_positions(report_input.positions)
        cache = ReportCache(
            Path(arguments.cache_dir), profile.chain_id, report_input.wallet,
            adapter_key=key,
        )
        rpc_endpoints = tuple(arguments.rpc) or adapter.default_rpc_endpoints
        client = JsonRpcClient(rpc_endpoints) if activities else None
        for activity in activities:
            if arguments.refresh or cache.receipt_needs_fetch(activity.transaction_hash):
                receipt = client.get_receipt(activity.transaction_hash) if client else None
                cache.put_receipt(activity.transaction_hash, receipt)
            receipt = cache.get_receipt(activity.transaction_hash)
            if receipt is None:
                warnings.append(f"receipt_unavailable:{activity.transaction_hash}")
                transactions.append(unavailable_transaction(activity, "receipt_unavailable"))
                continue
            try:
                decoded = adapter.decode_receipt(
                    activity, receipt, report_input.positions
                )
            except ValueError as error:
                reason = str(error)
                warnings.append(f"decode_unavailable:{activity.transaction_hash}:{reason}")
                transactions.append(unavailable_transaction(activity, reason))
                continue
            priceable_indices.append(len(transactions))
            transactions.append(decoded)

    if priceable_indices and not arguments.no_prices:
        price_client = DefiLlamaPriceClient(
            base_url=arguments.price_api_base, cache=cache
        )
        price_requests = collect_price_requests(
            (transactions[index] for index in priceable_indices),
            profile.native_price_token_address,
            price_token_resolver=adapter.normalize_price_token,
        )
        quotes = price_client.get_quotes(
            price_requests, chain_slug=adapter.price_chain_slug
        )
        for index in priceable_indices:
            transactions[index] = value_transaction(
                transactions[index],
                quotes,
                native_price_token=profile.native_price_token_address,
                price_token_resolver=adapter.normalize_price_token,
            )
        warnings.extend(price_client.diagnostics)

    capital = aggregate_daily_capital(
        report_input.positions,
        report_input.capital_points,
        report_input.start,
        report_input.end,
    )
    diagnostics = Diagnostics(
        warnings=tuple(warnings + (cache.diagnostics if cache else [])),
        reasons=("chain_protocol_unsupported",) if adapter is None else (),
        rpc_endpoints=rpc_endpoints if activities else (),
    )
    report = build_report(report_input, transactions, capital, diagnostics)
    report = _annotate_unavailable(report, adapter is None)
    output = Path(arguments.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_report_json(report, output / "report.json")
    (output / "report.html").write_text(
        render_html(report), encoding="utf-8", newline="\n"
    )
    return 0


def _annotate_unavailable(report: Report, unsupported: bool) -> Report:
    explicit_reasons = {
        "chain_protocol_unsupported", "receipt_unavailable",
        "native_claim_unavailable", "claim_principal_separation_unavailable",
        "native_fee_unavailable",
        "fee_attribution_ambiguous", "pool_identity_mismatch",
        "unknown_token_decimals",
    }
    reasons_by_day: dict[date, set[str]] = {}
    non_claim_blocked_days: set[date] = set()
    for transaction in report.transactions:
        action = transaction.action_type.strip().lower().replace("-", "_")
        transaction_reasons: set[str] = set()
        for valuation in (
            transaction.gross_claim_usd, transaction.automation_fee_usd,
            transaction.net_compound_usd, transaction.gas_account_debit_usd,
        ):
            if valuation.reason in explicit_reasons:
                transaction_reasons.add(valuation.reason)
        transaction_reasons.update(
            warning for warning in transaction.warnings
            if warning in explicit_reasons
        )
        if any(
            warning.startswith("unknown_token_decimals:")
            for warning in transaction.warnings
        ):
            transaction_reasons.add("unknown_token_decimals")
        if not transaction_reasons:
            continue
        reasons_by_day.setdefault(transaction.timestamp.date(), set()).update(
            transaction_reasons
        )
        if action not in CLAIM_ACTIONS:
            non_claim_blocked_days.add(transaction.timestamp.date())
    days = []
    for day in report.days:
        reasons = set(reasons_by_day.get(day.day, ()))
        if unsupported:
            reasons.add("chain_protocol_unsupported")
        if not reasons:
            days.append(day)
            continue
        changes = {"reasons": tuple(dict.fromkeys((*day.reasons, *sorted(reasons))))}
        if reasons & explicit_reasons:
            changes["realized_apr_percent"] = None
        if day.day in non_claim_blocked_days:
            changes.update(
                gross_claim_usd=None, net_compound_usd=None,
                automation_fee_usd=None, net_claim_usd=None,
            )
        if unsupported:
            changes.update(
                gross_claim_usd=None, net_compound_usd=None,
                automation_fee_usd=None, gas_account_debit_usd=None,
                net_claim_usd=None, realized_apr_percent=None,
            )
        days.append(replace(day, **changes))
    return replace(report, days=tuple(days))


def profile_for_positions(
    profile: ChainProfile, positions: Iterable[PositionInput]
) -> ChainProfile:
    """Compatibility entry point for callers passing an explicit HyperEVM profile."""
    from .adapters.hyperevm_nest import profile_for_positions as enrich_profile

    return enrich_profile(profile, positions)


def _parse_now(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)
