from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from ..contracts import PositionInput
from ..events import ChainProfile, DecodedTransaction, MergedActivity


_ADAPTER_KEY = re.compile(r"^([1-9][0-9]*):([A-Za-z][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class AdapterKey:
    chain_id: int
    protocol_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_type", self.protocol_type.lower())

    @classmethod
    def parse(cls, value: str) -> AdapterKey:
        match = _ADAPTER_KEY.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            raise AdapterResolutionError("invalid_adapter_override")
        return cls(int(match.group(1)), match.group(2))

    def __str__(self) -> str:
        return f"{self.chain_id}:{self.protocol_type}"


class AdapterResolutionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@runtime_checkable
class ReportAdapter(Protocol):
    @property
    def key(self) -> AdapterKey: ...

    @property
    def chain_profile(self) -> ChainProfile: ...

    @property
    def default_rpc_endpoints(self) -> tuple[str, ...]: ...

    @property
    def price_chain_slug(self) -> str: ...

    def normalize_price_token(self, address: str) -> str: ...

    def supports_position(self, position: PositionInput) -> bool: ...

    def profile_for_positions(self, positions: tuple[PositionInput, ...]) -> ChainProfile: ...

    def decode_receipt(
        self,
        activity: MergedActivity,
        receipt: Mapping[str, Any],
        positions: tuple[PositionInput, ...],
    ) -> DecodedTransaction: ...
