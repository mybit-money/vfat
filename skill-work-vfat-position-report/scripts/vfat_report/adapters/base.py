from __future__ import annotations

import re
from dataclasses import dataclass


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
