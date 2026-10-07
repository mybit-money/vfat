from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from vfat_report.adapters.base import AdapterKey
from vfat_report.cache import ReportCache
from vfat_report.rpc import JsonRpcClient, RateLimiter


TX_HASH = "0x" + "ab" * 32
WALLET = "0x330d2a845d2df4e329034d72719c7c53f9c1f87a"


class MutableClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class CacheRpcTests(unittest.TestCase):
    def test_same_chain_protocols_isolate_receipts_prices_and_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = ReportCache(root, 999, WALLET)
            legacy.put_receipt(TX_HASH, {"owner": "legacy"})
            legacy.put_snapshot("price_abc_123", {"priceUsd": "2"})
            nest = ReportCache(root, 999, WALLET, adapter_key=AdapterKey(999, "nest"))
            other = ReportCache(root, 999, WALLET, adapter_key=AdapterKey(999, "other"),
                                legacy_read_root=legacy.root)
            foreign_nest = ReportCache(root, 1, WALLET, adapter_key=AdapterKey(1, "nest"),
                                       legacy_read_root=legacy.root)
            self.assertEqual(nest.get_receipt(TX_HASH), {"owner": "legacy"})
            self.assertEqual(nest.get_snapshot("price_abc_123"), {"priceUsd": "2"})
            for isolated in (other, foreign_nest):
                self.assertIsNone(isolated.get_receipt(TX_HASH))
                self.assertTrue(isolated.receipt_needs_fetch(TX_HASH))
                self.assertIsNone(isolated.get_snapshot("price_abc_123"))

            nest.put_receipt(TX_HASH, {"owner": "nest"})
            nest.put_snapshot("price_abc_123", {"priceUsd": "3"})
            self.assertIsNone(other.get_receipt(TX_HASH))
            self.assertIsNone(other.get_snapshot("price_abc_123"))
            other.put_receipt(TX_HASH, {"owner": "other"})
            other.put_snapshot("price_abc_123", {"priceUsd": "4"})
            self.assertEqual(nest.get_receipt(TX_HASH), {"owner": "nest"})
            self.assertEqual(nest.get_snapshot("price_abc_123"), {"priceUsd": "3"})
            self.assertEqual(other.get_receipt(TX_HASH), {"owner": "other"})
            self.assertEqual(other.get_snapshot("price_abc_123"), {"priceUsd": "4"})
            self.assertEqual(legacy.get_receipt(TX_HASH), {"owner": "legacy"})
            self.assertEqual(legacy.get_snapshot("price_abc_123"), {"priceUsd": "2"})

    def test_adapter_cache_rejects_unsafe_or_mismatched_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                ReportCache(root, 999, WALLET, adapter_key=AdapterKey(1, "uniswap_v4"))
            with self.assertRaises(ValueError):
                ReportCache(root, 999, WALLET, adapter_key=AdapterKey(999, ".."))

    def test_adapter_cache_roots_isolate_the_same_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nest = ReportCache(root, 999, WALLET, adapter_key=AdapterKey(999, "nest"))
            v4 = ReportCache(root, 1, WALLET, adapter_key=AdapterKey(1, "uniswap_v4"))

            nest.put_receipt(TX_HASH, {"chain": 999})
            v4.put_receipt(TX_HASH, {"chain": 1})

            self.assertEqual(nest.receipt_path(TX_HASH), root / "999" / "nest" / WALLET / "receipts" / f"{TX_HASH}.json")
            self.assertEqual(v4.receipt_path(TX_HASH), root / "1" / "uniswap_v4" / WALLET / "receipts" / f"{TX_HASH}.json")
            self.assertEqual(nest.get_receipt(TX_HASH), {"chain": 999})
            self.assertEqual(v4.get_receipt(TX_HASH), {"chain": 1})

    def test_only_nest_reads_legacy_receipts_and_price_snapshots_without_writing_there(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = ReportCache(root, 999, WALLET)
            legacy.put_receipt(TX_HASH, {"status": "legacy"})
            legacy.put_snapshot("price_abc_123", {"priceUsd": "2"})
            nest = ReportCache(root, 999, WALLET, adapter_key=AdapterKey(999, "nest"))
            v4 = ReportCache(root, 1, WALLET, adapter_key=AdapterKey(1, "uniswap_v4"))

            self.assertEqual(nest.get_receipt(TX_HASH), {"status": "legacy"})
            self.assertFalse(nest.receipt_needs_fetch(TX_HASH))
            self.assertEqual(nest.get_snapshot("price_abc_123"), {"priceUsd": "2"})
            self.assertIsNone(v4.get_receipt(TX_HASH))
            self.assertIsNone(v4.get_snapshot("price_abc_123"))

            nest.put_receipt(TX_HASH, {"status": "new"})
            nest.put_snapshot("price_abc_123", {"priceUsd": "3"})

            self.assertEqual(legacy.get_receipt(TX_HASH), {"status": "legacy"})
            self.assertEqual(legacy.get_snapshot("price_abc_123"), {"priceUsd": "2"})
            self.assertEqual(nest.get_receipt(TX_HASH), {"status": "new"})
            self.assertEqual(nest.get_snapshot("price_abc_123"), {"priceUsd": "3"})

    def test_rate_limiter_never_exceeds_100_requests_per_rolling_minute(self) -> None:
        limiter = RateLimiter(max_requests=100, period_seconds=60)

        waits = [limiter.acquire(0.0) for _ in range(101)]

        self.assertEqual(waits[:100], [0.0] * 100)
        self.assertEqual(waits[100], 60.0)
        self.assertEqual(limiter.acquire(60.0), 0.0)

    def test_rpc_retries_retryable_errors_and_uses_backup(self) -> None:
        calls: list[str] = []

        def transport(endpoint: str, payload: dict) -> dict:
            calls.append(endpoint)
            if endpoint == "https://primary.invalid":
                raise OSError("temporary failure")
            return {"jsonrpc": "2.0", "id": payload["id"], "result": {"status": "0x1"}}

        clock = MutableClock()
        client = JsonRpcClient(
            ("https://primary.invalid", "https://backup.invalid"),
            transport=transport,
            limiter=RateLimiter(100, 60),
            clock=clock,
            sleep=clock.sleep,
            max_attempts_per_endpoint=1,
        )

        receipt = client.get_receipt(TX_HASH)

        self.assertEqual(receipt, {"status": "0x1"})
        self.assertEqual(calls, ["https://primary.invalid", "https://backup.invalid"])

    def test_successful_receipt_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = ReportCache(Path(temporary), 999, WALLET)
            cache.put_receipt(TX_HASH, {"status": "0x1"})
            cache.put_receipt(TX_HASH, {"status": "0x0"})

            self.assertEqual(cache.get_receipt(TX_HASH), {"status": "0x1"})

    def test_missing_receipt_has_short_ttl(self) -> None:
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            cache = ReportCache(Path(temporary), 999, WALLET, now=lambda: now)
            cache.put_receipt(TX_HASH, None)

            self.assertFalse(cache.receipt_needs_fetch(TX_HASH))
            later = now + timedelta(minutes=6)
            expired = ReportCache(Path(temporary), 999, WALLET, now=lambda: later)
            self.assertTrue(expired.receipt_needs_fetch(TX_HASH))

    def test_recent_three_days_are_marked_for_refresh(self) -> None:
        today = date(2026, 10, 3)

        self.assertTrue(ReportCache.should_refresh_day(date(2026, 10, 3), today))
        self.assertTrue(ReportCache.should_refresh_day(date(2026, 10, 1), today))
        self.assertFalse(ReportCache.should_refresh_day(date(2026, 9, 30), today))

    def test_cache_invalidates_derived_layer_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = ReportCache(root, 999, WALLET, calculation_version="1")
            old.put_receipt(TX_HASH, {"status": "0x1"})
            old.put_snapshot("capital", {"points": [1]})
            old.put_daily(date(2026, 10, 1), {"apr": "12"})

            new = ReportCache(root, 999, WALLET, calculation_version="2")

            self.assertEqual(new.get_receipt(TX_HASH), {"status": "0x1"})
            self.assertEqual(new.get_snapshot("capital"), {"points": [1]})
            self.assertIsNone(new.get_daily(date(2026, 10, 1)))

    def test_corrupt_cache_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = ReportCache(Path(temporary), 999, WALLET)
            path = cache.receipt_path(TX_HASH)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{broken", encoding="utf-8")

            self.assertIsNone(cache.get_receipt(TX_HASH))
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob(path.name + ".corrupt-*"))), 1)
            self.assertTrue(any(item.startswith("corrupt_cache:") for item in cache.diagnostics))


if __name__ == "__main__":
    unittest.main()
