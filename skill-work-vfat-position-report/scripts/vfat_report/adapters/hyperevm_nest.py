from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from .base import AdapterKey
from ..contracts import PositionInput, TokenAmount, Valuation
from ..events import (
    ChainProfile,
    DecodedTransaction,
    MergedActivity,
    TokenMetadata,
    TRANSFER_TOPIC,
    _data_words,
    _hex_int,
    _topic_address,
    _unique_logs,
    load_chain_profile,
)


MINT_TOPIC = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"


def profile_for_positions(
    profile: ChainProfile, positions: Iterable[PositionInput]
) -> ChainProfile:
    matching_positions = tuple(
        position for position in positions if position.chain_id == profile.chain_id
    )
    tracked = frozenset(
        position.sickle_address.lower() for position in matching_positions
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
        tokens=tokens,
        pools=pools,
    )


def decode_receipt_with_profile(
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
    lp_additions: dict[str, int] = {}
    gas_account_debit_native: Decimal | None = None
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
        elif topics[0] == MINT_TOPIC and address in profile.pools:
            words = _data_words(log.get("data", "0x"))
            if len(words) >= 4:
                token0, token1 = profile.pools[address]
                lp_additions[token0] = lp_additions.get(token0, 0) + int(words[2], 16)
                lp_additions[token1] = lp_additions.get(token1, 0) + int(words[3], 16)

        for event in profile.gas_account_debit_events:
            if address == event.address and topics[0] == event.topic0:
                words = _data_words(log.get("data", "0x"))
                if len(words) > max(event.payer_word, event.amount_word):
                    raw_amount = int(words[event.amount_word], 16)
                    amount = Decimal(raw_amount) / (Decimal(10) ** event.decimals)
                    gas_account_debit_native = (gas_account_debit_native or Decimal(0)) + amount

    fee_rate = _effective_fee_rate(gross, fees)
    if (
        fee_rate is not None
        and abs(fee_rate - profile.expected_automation_fee_rate) > Decimal("1e-12")
    ):
        warnings.append("automation_fee_rate_differs_from_expected")
    if activity.automation_payment_method == "gas-account" and gas_account_debit_native is None:
        warnings.append("gas_account_debit_unavailable")

    gas_used = _hex_int(receipt.get("gasUsed", "0x0"))
    gas_price = _hex_int(receipt.get("effectiveGasPrice", "0x0"))
    network_gas = Decimal(gas_used * gas_price) / (Decimal(10) ** profile.native_decimals)
    gas_debit_valuation = (
        Valuation(None, reason="historical_native_usd_unavailable")
        if gas_account_debit_native is not None
        else Valuation(
            Decimal(0),
            source="none",
            reason="gas_account_debit_unavailable"
            if activity.automation_payment_method == "gas-account"
            else None,
        )
    )
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


def _load_profile() -> ChainProfile:
    return load_chain_profile(Path(__file__).resolve().parents[3] / "profiles" / "hyperevm-nest.json")


@dataclass(frozen=True)
class HyperEvmNestAdapter:
    key: AdapterKey = AdapterKey(999, "nest")
    chain_profile: ChainProfile = field(default_factory=_load_profile)
    default_rpc_endpoints: tuple[str, ...] = (
        "https://rpc.hyperliquid.xyz/evm",
        "https://rpc.hypurrscan.io",
    )
    price_chain_slug: str = "hyperliquid"

    def normalize_price_token(self, address: str) -> str:
        return address.lower()

    def supports_position(self, position: PositionInput) -> bool:
        if position.chain_id != self.key.chain_id:
            return False
        metadata = position.metadata if isinstance(position.metadata, Mapping) else {}
        protocol_type = metadata.get("protocolType")
        return (
            protocol_type.lower() == self.key.protocol_type
            if isinstance(protocol_type, str)
            else position.protocol.lower() == self.key.protocol_type
        )

    def profile_for_positions(self, positions: tuple[PositionInput, ...]) -> ChainProfile:
        return profile_for_positions(self.chain_profile, positions)

    def decode_receipt(
        self,
        activity: MergedActivity,
        receipt: Mapping[str, Any],
        positions: tuple[PositionInput, ...],
    ) -> DecodedTransaction:
        return decode_receipt_with_profile(
            activity, receipt, self.profile_for_positions(positions)
        )
