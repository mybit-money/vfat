from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import ActivityInput, NormalizedTransaction


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


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
                action_type=items[0].action_type,
                source_position_ids=tuple(sources),
                recipient_position_ids=tuple(sorted(set(recipients))),
                is_automation=any(item.is_automation for item in items),
                automation_payment_method=sorted(methods)[0] if methods else None,
            )
        )
    return sorted(merged, key=lambda item: (item.timestamp, item.chain_id, item.transaction_hash))


def decode_receipt(
    activity: MergedActivity,
    receipt: Mapping[str, Any],
    profile: ChainProfile,
) -> DecodedTransaction:
    """Compatibility entry point for callers passing an explicit HyperEVM profile."""
    from .adapters.hyperevm_nest import decode_receipt_with_profile

    return decode_receipt_with_profile(activity, receipt, profile)


def _unique_logs(transaction_hash: str, logs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[tuple[str, int]] = set()
    unique: list[Mapping[str, Any]] = []
    for log in logs:
        key = (transaction_hash, _hex_int(log.get("logIndex", "0x0")))
        if key not in seen:
            seen.add(key)
            unique.append(log)
    return unique


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
