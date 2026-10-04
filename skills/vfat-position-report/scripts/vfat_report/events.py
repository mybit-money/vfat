from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import (
    CLAIM_ACTIONS,
    COMPOUND_ACTIONS,
    ActivityInput,
    NormalizedTransaction,
    TokenAmount,
    Valuation,
    normalize_action,
)


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
MINT_TOPIC = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
# Algebra-style position manager: IncreaseLiquidity(uint256 indexed tokenId, ...).
INCREASE_LIQUIDITY_TOPIC = "0x8a82de7fe9b33e0e6bca0e26f5bd14a74f1164ffe236d50e0a36c3ea70f2b814"


@dataclass(frozen=True)
class TokenMetadata:
    symbol: str | None
    decimals: int


@dataclass(frozen=True)
class GasAccountDebitEvent:
    address: str
    topic0: str
    payer_word: int
    amount_word: int
    decimals: int


@dataclass(frozen=True)
class ChainProfile:
    chain_id: int
    native_symbol: str
    native_decimals: int
    native_price_token_address: str | None
    tracked_sickle_addresses: frozenset[str]
    claim_source_addresses: frozenset[str]
    automation_fee_recipients: frozenset[str]
    tokens: Mapping[str, TokenMetadata]
    pools: Mapping[str, tuple[str, str]]
    gas_account_debit_events: tuple[GasAccountDebitEvent, ...]
    expected_automation_fee_rate: Decimal
    tracked_positions: frozenset[tuple[str, int]] = frozenset()


@dataclass(frozen=True)
class MergedActivity:
    chain_id: int
    transaction_hash: str
    timestamp: datetime
    action_type: str
    source_position_ids: tuple[str, ...]
    recipient_position_ids: tuple[str, ...]
    is_automation: bool
    automation_payment_method: str | None


@dataclass(frozen=True)
class DecodedTransaction(NormalizedTransaction):
    effective_automation_fee_rate: Decimal | None = None
    gas_account_debit_native: Decimal | None = None


def load_chain_profile(path: Path) -> ChainProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tokens = {
        address.lower(): TokenMetadata(item.get("symbol"), int(item["decimals"]))
        for address, item in payload.get("tokens", {}).items()
    }
    pools = {
        address.lower(): (item["token0"].lower(), item["token1"].lower())
        for address, item in payload.get("pools", {}).items()
    }
    gas_events = tuple(
        GasAccountDebitEvent(
            address=item["address"].lower(),
            topic0=item["topic0"].lower(),
            payer_word=int(item["payerWord"]),
            amount_word=int(item["amountWord"]),
            decimals=int(item.get("decimals", payload["nativeToken"]["decimals"])),
        )
        for item in payload.get("gasAccountDebitEvents", [])
    )
    return ChainProfile(
        chain_id=int(payload["chainId"]),
        native_symbol=str(payload["nativeToken"]["symbol"]),
        native_decimals=int(payload["nativeToken"]["decimals"]),
        native_price_token_address=(
            str(payload["nativeToken"].get("priceTokenAddress")).lower()
            if payload["nativeToken"].get("priceTokenAddress")
            else None
        ),
        tracked_sickle_addresses=frozenset(
            value.lower() for value in payload.get("trackedSickleAddresses", [])
        ),
        claim_source_addresses=frozenset(
            value.lower() for value in payload.get("claimSourceAddresses", [])
        ),
        automation_fee_recipients=frozenset(
            value.lower() for value in payload.get("automationFeeRecipients", [])
        ),
        tokens=tokens,
        pools=pools,
        gas_account_debit_events=gas_events,
        expected_automation_fee_rate=Decimal(str(payload["expectedAutomationFeeRate"])),
    )


def merge_position_activity(records: Iterable[ActivityInput]) -> list[MergedActivity]:
    grouped: dict[tuple[int, str], list[ActivityInput]] = {}
    for record in records:
        grouped.setdefault((record.chain_id, record.transaction_hash.lower()), []).append(record)

    merged: list[MergedActivity] = []
    for (chain_id, transaction_hash), items in grouped.items():
        methods = {item.automation_payment_method for item in items if item.automation_payment_method}
        actions = sorted({item.action_type for item in items})
        sources = sorted({source for item in items for source in item.source_position_ids})
        recipients = sorted(
            item.recipient_position_id
            for item in items
            if item.recipient_position_id is not None
        )
        merged.append(
            MergedActivity(
                chain_id=chain_id,
                transaction_hash=transaction_hash,
                timestamp=min(item.timestamp for item in items),
                # The recipient feed may label a compound as "increased"; the claim label wins.
                action_type=next(
                    (action for action in actions if normalize_action(action) in CLAIM_ACTIONS),
                    actions[0],
                ),
                source_position_ids=tuple(sources),
                recipient_position_ids=tuple(sorted(set(recipients))),
                is_automation=any(item.is_automation for item in items),
                # On conflict keep gas-account so a missing debit stays unknown, not zero.
                automation_payment_method=(
                    "gas-account" if "gas-account" in methods else min(methods, default=None)
                ),
            )
        )
    return sorted(merged, key=lambda item: (item.timestamp, item.chain_id, item.transaction_hash))


def decode_receipt(
    activity: MergedActivity,
    receipt: Mapping[str, Any],
    profile: ChainProfile,
) -> DecodedTransaction:
    receipt_hash = str(receipt.get("transactionHash", "")).lower()
    if receipt_hash != activity.transaction_hash.lower():
        raise ValueError("receipt transactionHash does not match activity")
    if activity.chain_id != profile.chain_id:
        raise ValueError("activity chain does not match chain profile")

    gross: dict[str, int] = {}
    fees: dict[str, int] = {}
    fee_transfers: dict[str, int] = {}
    lp_additions: dict[str, int] = {}
    pending_mints: dict[str, tuple[str, int, int]] = {}
    gas_debits: list[Decimal] = []
    warnings: list[str] = []

    for log in _unique_logs(receipt_hash, receipt.get("logs", [])):
        address = str(log.get("address", "")).lower()
        topics = [str(value).lower() for value in log.get("topics", [])]
        if not topics:
            continue
        if topics[0] == TRANSFER_TOPIC and len(topics) >= 3 and address in profile.tokens:
            sender = _topic_address(topics[1])
            recipient = _topic_address(topics[2])
            amount = _hex_int(log.get("data", "0x0"))
            if sender in profile.claim_source_addresses and recipient in profile.tracked_sickle_addresses:
                gross[address] = gross.get(address, 0) + amount
            if sender in profile.tracked_sickle_addresses and recipient in profile.automation_fee_recipients:
                fees[address] = fees.get(address, 0) + amount
                fee_transfers[address] = fee_transfers.get(address, 0) + 1
        elif topics[0] == MINT_TOPIC and address in profile.pools and len(topics) >= 2:
            words = _data_words(log.get("data", "0x"))
            if len(words) >= 4:
                owner = _topic_address(topics[1])
                pending_mints[owner] = (address, int(words[2], 16), int(words[3], 16))
        elif topics[0] == INCREASE_LIQUIDITY_TOPIC and len(topics) >= 2:
            # The position manager emits IncreaseLiquidity right after the pool Mint it
            # caused; count the Mint only when that tokenId belongs to a tracked position.
            mint = pending_mints.pop(address, None)
            if mint and (address, int(topics[1], 16)) in profile.tracked_positions:
                pool, amount0, amount1 = mint
                token0, token1 = profile.pools[pool]
                lp_additions[token0] = lp_additions.get(token0, 0) + amount0
                lp_additions[token1] = lp_additions.get(token1, 0) + amount1

        for event in profile.gas_account_debit_events:
            if address == event.address and topics[0] == event.topic0:
                words = _data_words(log.get("data", "0x"))
                if len(words) > max(event.payer_word, event.amount_word):
                    raw_amount = int(words[event.amount_word], 16)
                    gas_debits.append(Decimal(raw_amount) / (Decimal(10) ** event.decimals))

    gas_account_debit_native = gas_debits[0] if len(gas_debits) == 1 else None
    if len(gas_debits) > 1:
        # ponytail: the debit event names the keeper, not the portfolio, so several debits
        # in one receipt cannot be attributed; match the per-Sickle event if batches appear.
        warnings.append("gas_account_debit_ambiguous")

    fee_rate = _effective_fee_rate(gross, fees)
    # Each fee transfer may be floored independently, so allow one raw unit per transfer.
    if any(
        abs(Decimal(fee) - Decimal(gross[token]) * profile.expected_automation_fee_rate)
        > fee_transfers[token]
        for token, fee in fees.items()
        if gross.get(token)
    ):
        warnings.append("automation_fee_rate_differs_from_expected")
    if activity.automation_payment_method == "fee" and gross and not fees:
        warnings.append("automation_fee_transfer_not_found")
    if normalize_action(activity.action_type) in COMPOUND_ACTIONS and not lp_additions:
        warnings.append("lp_addition_not_found")
    if activity.automation_payment_method == "gas-account" and gas_account_debit_native is None:
        warnings.append("gas_account_debit_unavailable")

    gas_used = _hex_int(receipt.get("gasUsed", "0x0"))
    gas_price = _hex_int(receipt.get("effectiveGasPrice", "0x0"))
    network_gas = Decimal(gas_used * gas_price) / (Decimal(10) ** profile.native_decimals)
    if gas_account_debit_native is not None:
        gas_debit_valuation = Valuation(None, reason="historical_native_usd_unavailable")
    elif gas_debits or activity.automation_payment_method == "gas-account":
        gas_debit_valuation = Valuation(None, reason="gas_account_debit_unavailable")
    else:
        gas_debit_valuation = Valuation(Decimal(0), source="none")
    return DecodedTransaction(
        chain_id=activity.chain_id,
        transaction_hash=activity.transaction_hash.lower(),
        timestamp=activity.timestamp,
        action_type=activity.action_type,
        source_position_ids=activity.source_position_ids,
        recipient_position_ids=activity.recipient_position_ids,
        automation_payment_method=activity.automation_payment_method,
        gross_claims=_token_amounts(gross, profile),
        automation_fees=_token_amounts(fees, profile),
        lp_additions=_token_amounts(lp_additions, profile),
        gross_claim_usd=Valuation(None, reason="historical_reward_usd_unavailable"),
        net_compound_usd=Valuation(None, reason="historical_lp_usd_unavailable"),
        gas_account_debit_usd=gas_debit_valuation,
        network_gas_native=network_gas,
        network_gas_payer=str(receipt.get("from", "")).lower() or None,
        warnings=tuple(warnings),
        effective_automation_fee_rate=fee_rate,
        gas_account_debit_native=gas_account_debit_native,
    )


def _unique_logs(transaction_hash: str, logs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[tuple[str, int]] = set()
    unique: list[Mapping[str, Any]] = []
    for log in logs:
        key = (transaction_hash, _hex_int(log.get("logIndex", "0x0")))
        if key not in seen:
            seen.add(key)
            unique.append(log)
    return unique


def _token_amounts(amounts: Mapping[str, int], profile: ChainProfile) -> tuple[TokenAmount, ...]:
    return tuple(
        TokenAmount(address, profile.tokens[address].symbol, profile.tokens[address].decimals, raw)
        for address, raw in sorted(amounts.items())
    )


def _effective_fee_rate(gross: Mapping[str, int], fees: Mapping[str, int]) -> Decimal | None:
    relevant = [(gross[token], fee) for token, fee in fees.items() if gross.get(token)]
    if not relevant:
        return None
    return Decimal(sum(gross_value for gross_value, _ in relevant)) and (
        Decimal(sum(fee_value for _, fee_value in relevant))
        / Decimal(sum(gross_value for gross_value, _ in relevant))
    )


def _topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def _hex_int(value: Any) -> int:
    return value if isinstance(value, int) else int(str(value), 16)


def _data_words(data: Any) -> list[str]:
    text = str(data)
    body = text[2:] if text.startswith("0x") else text
    if len(body) % 64:
        raise ValueError("event data length is not a multiple of 32 bytes")
    return [body[index : index + 64] for index in range(0, len(body), 64)]
