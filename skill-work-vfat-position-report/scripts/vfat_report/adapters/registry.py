from __future__ import annotations

from typing import Mapping

from .base import AdapterKey, AdapterResolutionError, ReportAdapter
from .hyperevm_nest import HyperEvmNestAdapter
from ..contracts import PositionInput


_ADAPTERS: Mapping[AdapterKey, ReportAdapter] = {
    AdapterKey(999, "nest"): HyperEvmNestAdapter(),
}


def get_adapter(key: AdapterKey) -> ReportAdapter | None:
    return _ADAPTERS.get(key)


def derive_adapter_key(
    position: PositionInput, report_protocols: tuple[str, ...]
) -> AdapterKey:
    metadata = position.metadata
    protocol_type = metadata.get("protocolType") if isinstance(metadata, Mapping) else None
    if protocol_type is None and position.chain_id == 999 and report_protocols == ("nest",):
        protocol_type = "nest"
    if not isinstance(protocol_type, str) or not protocol_type.strip():
        raise AdapterResolutionError("adapter_protocol_type_required")
    return AdapterKey(position.chain_id, protocol_type.strip())


def resolve_adapter_key(
    positions: tuple[PositionInput, ...],
    report_protocols: tuple[str, ...],
    override: str | None = None,
) -> AdapterKey:
    if not positions:
        raise AdapterResolutionError("report_adapter_unresolved")
    keys = {derive_adapter_key(position, report_protocols) for position in positions}
    if len(keys) != 1:
        raise AdapterResolutionError("mixed_report_adapters_unsupported")
    key = keys.pop()
    if override is not None and AdapterKey.parse(override) != key:
        raise AdapterResolutionError("adapter_override_mismatch")
    return key
