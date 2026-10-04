from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .aggregate import build_report
from .cache import ReportCache
from .capital import aggregate_daily_capital
from .contracts import (
    ActivityInput,
    Diagnostics,
    NormalizedTransaction,
    PositionInput,
    load_report_input,
    write_report_json,
)
from .events import (
    ChainProfile,
    TokenMetadata,
    decode_receipt,
    load_chain_profile,
    merge_position_activity,
)
from .html_report import render_html
from .prices import DefiLlamaPriceClient, collect_price_requests, value_transaction
from .rpc import JsonRpcClient


DEFAULT_RPCS = ("https://rpc.hyperliquid.xyz/evm", "https://rpc.hypurrscan.io")


def run(arguments: Namespace) -> int:
    explicit_now = _parse_now(arguments.now) if arguments.now else None
    report_input = load_report_input(Path(arguments.input), now=explicit_now)
    skill_root = Path(__file__).resolve().parents[2]
    profile = load_chain_profile(skill_root / "profiles" / "hyperevm-nest.json")
    warnings = [
        f"chain_unsupported:{chain_id}"
        for chain_id in report_input.chain_ids
        if chain_id != profile.chain_id
    ]
    chain_selected = profile.chain_id in report_input.chain_ids
    positions = tuple(
        position
        for position in report_input.positions
        if chain_selected
        and position.chain_id == profile.chain_id
        and position.protocol in report_input.protocols
    )
    profile = profile_for_positions(profile, positions)
    excluded_ids = {item.position_id for item in report_input.positions} - {
        item.position_id for item in positions
    }
    cache = ReportCache(Path(arguments.cache_dir), profile.chain_id, report_input.wallet)
    activities = merge_position_activity(
        item
        for item in report_input.activities
        if chain_selected
        and item.chain_id == profile.chain_id
        and report_input.start <= item.timestamp < report_input.end
        and not _only_excluded_positions(item, excluded_ids)
    )
    transactions: list[NormalizedTransaction] = []
    rpc_endpoints = tuple(arguments.rpc) or DEFAULT_RPCS
    client = JsonRpcClient(rpc_endpoints)
    for activity in activities:
        tx_hash = activity.transaction_hash
        # Successful receipts are immutable; --refresh only bypasses the missing-receipt TTL.
        if cache.receipt_needs_fetch(tx_hash) or (
            arguments.refresh and cache.get_receipt(tx_hash) is None
        ):
            try:
                cache.put_receipt(tx_hash, client.get_receipt(tx_hash))
            except RuntimeError:
                warnings.append(f"receipt_fetch_failed:{tx_hash}")
        receipt = cache.get_receipt(tx_hash)
        if receipt is None:
            warnings.append(f"receipt_unavailable:{tx_hash}")
            continue
        if receipt.get("status") == "0x0":
            warnings.append(f"transaction_reverted:{tx_hash}")
            continue
        transactions.append(decode_receipt(activity, receipt, profile))
    if report_input.reward_tokens:
        transactions = _select_reward_tokens(transactions, frozenset(report_input.reward_tokens))

    if transactions and not arguments.no_prices:
        price_client = DefiLlamaPriceClient(
            base_url=arguments.price_api_base, cache=cache
        )
        price_requests = collect_price_requests(
            transactions, profile.native_price_token_address
        )
        quotes = price_client.get_quotes(price_requests, chain_id=profile.chain_id)
        transactions = [
            value_transaction(
                transaction,
                quotes,
                native_price_token=profile.native_price_token_address,
            )
            for transaction in transactions
        ]
        warnings.extend(price_client.diagnostics)

    capital = aggregate_daily_capital(
        positions,
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
    matching_positions = tuple(
        position for position in positions if position.chain_id == profile.chain_id
    )
    tracked = frozenset(
        position.sickle_address.lower() for position in matching_positions
    )
    tracked_positions = frozenset(
        (position.nft_manager_address, int(position.token_id))
        for position in matching_positions
        if position.nft_manager_address and position.token_id and position.token_id.isdigit()
    )
    tokens = dict(profile.tokens)
    pools = dict(profile.pools)
    for position in matching_positions:
        metadata = position.metadata
        if not isinstance(metadata, dict):
            continue
        pool = metadata.get("poolAddress")
        underlying = metadata.get("underlying")
        if not isinstance(pool, str) or not isinstance(underlying, list):
            continue
        if len(underlying) < 2 or not all(
            isinstance(item, dict) for item in underlying[:2]
        ):
            continue
        token_addresses: list[str] = []
        for item in underlying[:2]:
            address = item.get("address")
            decimals = item.get("decimals")
            if not isinstance(address, str) or not isinstance(decimals, int):
                token_addresses = []
                break
            normalized = address.lower()
            tokens[normalized] = TokenMetadata(item.get("symbol"), decimals)
            token_addresses.append(normalized)
        if len(token_addresses) == 2:
            pools[pool.lower()] = (token_addresses[0], token_addresses[1])
    return replace(
        profile,
        tracked_sickle_addresses=tracked,
        tracked_positions=tracked_positions,
        tokens=tokens,
        pools=pools,
    )


def _only_excluded_positions(activity: ActivityInput, excluded_ids: set[str]) -> bool:
    referenced = set(activity.source_position_ids)
    if activity.recipient_position_id is not None:
        referenced.add(activity.recipient_position_id)
    return bool(referenced) and referenced <= excluded_ids


def _select_reward_tokens(
    transactions: Iterable[NormalizedTransaction], tokens: frozenset[str]
) -> list[NormalizedTransaction]:
    selected: list[NormalizedTransaction] = []
    for transaction in transactions:
        gross = tuple(item for item in transaction.gross_claims if item.token_address in tokens)
        if transaction.gross_claims and not gross:
            continue
        warnings = transaction.warnings
        if len(gross) < len(transaction.gross_claims):
            # ponytail: LP mints cannot be split by reward token; net compound stays whole.
            warnings += ("net_compound_includes_unselected_rewards",)
        selected.append(
            replace(
                transaction,
                gross_claims=gross,
                automation_fees=tuple(
                    item for item in transaction.automation_fees if item.token_address in tokens
                ),
                warnings=warnings,
            )
        )
    return selected


def _parse_now(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)
