from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from . import INPUT_SCHEMA_VERSION, REPORT_SCHEMA_VERSION


DEFAULT_WALLET = "0x330d2a845d2df4e329034d72719c7c53f9c1f87a"
DEFAULT_CHAIN_ID = 999
DEFAULT_PROTOCOL = "nest"
EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class PositionInput:
    position_id: str
    chain_id: int
    protocol: str
    position_type: str
    sickle_address: str
    token_id: str | None = None
    nft_manager_address: str | None = None
    active_from: datetime | None = None
    active_to: datetime | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ActivityInput:
    chain_id: int
    transaction_hash: str
    timestamp: datetime
    action_type: str
    source_position_ids: tuple[str, ...] = ()
    recipient_position_id: str | None = None
    is_automation: bool = False
    automation_payment_method: str | None = None


@dataclass(frozen=True)
class CapitalPoint:
    position_id: str
    timestamp: datetime
    current_balance_usd: Decimal


@dataclass(frozen=True)
class TokenAmount:
    token_address: str
    symbol: str | None
    decimals: int
    raw_amount: int

    @property
    def amount(self) -> Decimal:
        return Decimal(self.raw_amount) / (Decimal(10) ** self.decimals)


@dataclass(frozen=True)
class Valuation:
    usd: Decimal | None
    source: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class NormalizedTransaction:
    chain_id: int
    transaction_hash: str
    timestamp: datetime
    action_type: str
    source_position_ids: tuple[str, ...] = ()
    recipient_position_ids: tuple[str, ...] = ()
    automation_payment_method: str | None = None
    gross_claims: tuple[TokenAmount, ...] = ()
    automation_fees: tuple[TokenAmount, ...] = ()
    lp_additions: tuple[TokenAmount, ...] = ()
    gross_claim_usd: Valuation = Valuation(None, reason="unavailable")
    automation_fee_usd: Valuation = Valuation(None, reason="unavailable")
    net_compound_usd: Valuation = Valuation(None, reason="unavailable")
    gas_account_debit_usd: Valuation = Valuation(Decimal(0), source="none")
    network_gas_native: Decimal | None = None
    network_gas_payer: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DailyAggregate:
    day: date
    status: str
    average_capital_usd: Decimal | None
    capital_coverage: Decimal
    gross_claim_usd: Decimal | None
    net_compound_usd: Decimal | None
    automation_fee_usd: Decimal | None
    gas_account_debit_usd: Decimal | None
    realized_apr_percent: Decimal | None
    claim_transaction_count: int
    reward_amounts: tuple[TokenAmount, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnostics:
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    rpc_endpoints: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    schema_version: str
    generated_at: datetime
    input_summary: Mapping[str, Any]
    days: tuple[DailyAggregate, ...]
    transactions: tuple[NormalizedTransaction, ...]
    diagnostics: Diagnostics


@dataclass(frozen=True)
class ReportInput:
    schema_version: str
    wallet: str
    start: datetime
    end: datetime
    chain_ids: tuple[int, ...]
    protocols: tuple[str, ...]
    reward_tokens: tuple[str, ...]
    positions: tuple[PositionInput, ...]
    activities: tuple[ActivityInput, ...]
    capital_points: tuple[CapitalPoint, ...]
    source: Mapping[str, Any]


def _address(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not EVM_ADDRESS.fullmatch(value):
        raise ValueError(f"{field} must be a 20-byte EVM address")
    return value.lower()


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO 8601 timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO 8601 timestamp with a timezone") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone and use UTC")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def _default_window(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now_utc = now.astimezone(timezone.utc)
    start_day = now_utc.date() - timedelta(days=6)
    return datetime.combine(start_day, time.min, tzinfo=timezone.utc), now_utc


def load_report_input(path: Path, now: datetime | None = None) -> ReportInput:
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema_version = str(payload.get("schemaVersion", ""))
    if schema_version != INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"schemaVersion must be {INPUT_SCHEMA_VERSION}, got {schema_version or 'missing'}"
        )

    effective_now = now or datetime.now(timezone.utc)
    default_start, default_end = _default_window(effective_now)
    period = payload.get("period") or {}
    start = _timestamp(period["from"], "period.from") if "from" in period else default_start
    end = _timestamp(period["to"], "period.to") if "to" in period else default_end
    if start >= end:
        raise ValueError("period.from must be earlier than period.to")

    wallet = _address(payload.get("wallet", DEFAULT_WALLET), "wallet")
    filters = payload.get("filters") or {}
    chain_ids = tuple(int(value) for value in filters.get("chainIds", [DEFAULT_CHAIN_ID]))
    protocols = tuple(str(value).lower() for value in filters.get("protocols", [DEFAULT_PROTOCOL]))
    reward_tokens = tuple(
        _address(value, f"filters.rewardTokens[{index}]") or ""
        for index, value in enumerate(filters.get("rewardTokens", []))
    )

    positions: list[PositionInput] = []
    for index, item in enumerate(payload.get("positions", [])):
        active_from = (
            _timestamp(item["activeFrom"], f"positions[{index}].activeFrom")
            if item.get("activeFrom")
            else None
        )
        active_to = (
            _timestamp(item["activeTo"], f"positions[{index}].activeTo")
            if item.get("activeTo")
            else None
        )
        positions.append(
            PositionInput(
                position_id=str(item["positionId"]),
                chain_id=int(item["chainId"]),
                protocol=str(item["protocol"]).lower(),
                position_type=str(item["positionType"]).lower(),
                sickle_address=_address(
                    item.get("sickleAddress"), f"positions[{index}].sickleAddress"
                )
                or "",
                token_id=str(item["tokenId"]) if item.get("tokenId") is not None else None,
                nft_manager_address=_address(
                    item.get("nftManagerAddress"),
                    f"positions[{index}].nftManagerAddress",
                    optional=True,
                ),
                active_from=active_from,
                active_to=active_to,
                metadata=item.get("metadata"),
            )
        )

    activities: list[ActivityInput] = []
    for index, item in enumerate(payload.get("activities", [])):
        tx_hash = str(item.get("transactionHash", "")).lower()
        if not TX_HASH.fullmatch(tx_hash):
            raise ValueError(f"activities[{index}].transactionHash must be a 32-byte hash")
        activities.append(
            ActivityInput(
                chain_id=int(item["chainId"]),
                transaction_hash=tx_hash,
                timestamp=_timestamp(item["timestamp"], f"activities[{index}].timestamp"),
                action_type=str(item["actionType"]),
                source_position_ids=tuple(str(value) for value in item.get("sourcePositionIds", [])),
                recipient_position_id=(
                    str(item["recipientPositionId"])
                    if item.get("recipientPositionId") is not None
                    else None
                ),
                is_automation=bool(item.get("isAutomation", False)),
                automation_payment_method=item.get("automationPaymentMethod"),
            )
        )

    capital_points = tuple(
        CapitalPoint(
            position_id=str(item["positionId"]),
            timestamp=_timestamp(item["timestamp"], f"capitalPoints[{index}].timestamp"),
            current_balance_usd=Decimal(str(item["currentBalanceUsd"])),
        )
        for index, item in enumerate(payload.get("capitalPoints", []))
    )

    return ReportInput(
        schema_version=schema_version,
        wallet=wallet or "",
        start=start,
        end=end,
        chain_ids=chain_ids,
        protocols=protocols,
        reward_tokens=reward_tokens,
        positions=tuple(positions),
        activities=tuple(activities),
        capital_points=capital_points,
        source=payload.get("source") or {},
    )


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def report_to_dict(report: Report) -> dict[str, Any]:
    value = _json_value(report)
    value["schemaVersion"] = value.pop("schema_version")
    value["generatedAt"] = value.pop("generated_at")
    value["inputSummary"] = value.pop("input_summary")
    return value


def write_report_json(report: Report, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        report_to_dict(report), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    path.write_text(content, encoding="utf-8", newline="\n")
