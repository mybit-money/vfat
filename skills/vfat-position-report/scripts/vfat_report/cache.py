from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import CALCULATION_VERSION, INPUT_SCHEMA_VERSION


SAFE_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")


class ReportCache:
    def __init__(
        self,
        root: Path,
        chain_id: int,
        wallet: str,
        *,
        input_schema_version: str = INPUT_SCHEMA_VERSION,
        calculation_version: str = CALCULATION_VERSION,
        now: Callable[[], datetime] | None = None,
        missing_receipt_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        self.root = root / str(chain_id) / wallet.lower()
        self.input_schema_version = input_schema_version
        self.calculation_version = calculation_version
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.missing_receipt_ttl = missing_receipt_ttl
        self.diagnostics: list[str] = []

    def receipt_path(self, tx_hash: str) -> Path:
        key = tx_hash.lower().removeprefix("0x")
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("transaction hash must contain 32 bytes")
        return self.root / "receipts" / f"0x{key}.json"

    def get_receipt(self, tx_hash: str) -> Mapping[str, Any] | None:
        envelope = self._read(self.receipt_path(tx_hash))
        if not envelope or envelope.get("schemaVersion") != self.input_schema_version:
            return None
        if envelope.get("status") != "ok":
            return None
        data = envelope.get("data")
        return data if isinstance(data, Mapping) else None

    def receipt_needs_fetch(self, tx_hash: str) -> bool:
        path = self.receipt_path(tx_hash)
        envelope = self._read(path)
        if not envelope or envelope.get("schemaVersion") != self.input_schema_version:
            return True
        if envelope.get("status") == "ok":
            return False
        try:
            cached_at = datetime.fromisoformat(str(envelope["cachedAt"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return True
        return self.now().astimezone(timezone.utc) - cached_at > self.missing_receipt_ttl

    def put_receipt(self, tx_hash: str, receipt: Mapping[str, Any] | None) -> None:
        path = self.receipt_path(tx_hash)
        existing = self._read(path)
        if existing and existing.get("status") == "ok":
            return
        envelope: dict[str, Any] = {
            "schemaVersion": self.input_schema_version,
            "status": "ok" if receipt is not None else "missing",
            "cachedAt": _timestamp(self.now()),
        }
        if receipt is not None:
            envelope["data"] = dict(receipt)
        self._write(path, envelope)

    def get_snapshot(self, key: str) -> Mapping[str, Any] | None:
        envelope = self._read(self._layer_path("snapshots", key))
        if not envelope or envelope.get("schemaVersion") != self.input_schema_version:
            return None
        data = envelope.get("data")
        return data if isinstance(data, Mapping) else None

    def put_snapshot(self, key: str, data: Mapping[str, Any]) -> None:
        self._write(
            self._layer_path("snapshots", key),
            {"schemaVersion": self.input_schema_version, "data": dict(data)},
        )

    def get_daily(self, day: date) -> Mapping[str, Any] | None:
        envelope = self._read(self._layer_path("daily", day.isoformat()))
        if not envelope or envelope.get("calculationVersion") != self.calculation_version:
            return None
        data = envelope.get("data")
        return data if isinstance(data, Mapping) else None

    def put_daily(self, day: date, data: Mapping[str, Any]) -> None:
        self._write(
            self._layer_path("daily", day.isoformat()),
            {
                "schemaVersion": self.input_schema_version,
                "calculationVersion": self.calculation_version,
                "data": dict(data),
            },
        )

    @staticmethod
    def should_refresh_day(day: date, today: date) -> bool:
        return day >= today - timedelta(days=2)

    def _layer_path(self, layer: str, key: str) -> Path:
        if not SAFE_KEY.fullmatch(key):
            raise ValueError("cache key contains unsupported characters")
        return self.root / layer / f"{key}.json"

    def _read(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            suffix = self.now().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            quarantine = path.with_name(f"{path.name}.corrupt-{suffix}")
            path.replace(quarantine)
            self.diagnostics.append(f"corrupt_cache:{path}")
            return None

    @staticmethod
    def _write(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("cache timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
