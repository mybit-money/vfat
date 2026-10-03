from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from vfat_report.contracts import (
    DEFAULT_WALLET,
    Diagnostics,
    Report,
    load_report_input,
    write_report_json,
)


FIXTURES = Path(__file__).parent / "fixtures"


class ContractTests(unittest.TestCase):
    def test_load_minimal_input_applies_defaults(self) -> None:
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

        report_input = load_report_input(FIXTURES / "minimal-input.json", now=now)

        self.assertEqual(report_input.wallet, DEFAULT_WALLET)
        self.assertEqual(report_input.chain_ids, (999,))
        self.assertEqual(report_input.protocols, ("nest",))
        self.assertEqual(report_input.start.isoformat(), "2026-09-27T00:00:00+00:00")
        self.assertEqual(report_input.end, now)
        self.assertEqual(
            report_input.positions[0].sickle_address,
            "0x05a34ca31a38c136b8489d4147112cfc4a92a155",
        )
        self.assertEqual(
            report_input.positions[0].nft_manager_address,
            "0xeaf58788a405f3253814b4559391a22be8616250",
        )

    def test_future_period_end_is_clamped_to_now(self) -> None:
        base = json.loads((FIXTURES / "minimal-input.json").read_text(encoding="utf-8"))
        base["period"] = {"from": "2026-10-01T00:00:00Z", "to": "2026-10-06T00:00:00Z"}
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "future.json"
            path.write_text(json.dumps(base), encoding="utf-8")
            report_input = load_report_input(path, now=now)

        self.assertEqual(report_input.end, now)

    def test_rejects_invalid_wallet_or_non_utc_window(self) -> None:
        base = json.loads((FIXTURES / "minimal-input.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            base["wallet"] = "not-an-address"
            path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "wallet.*EVM address"):
                load_report_input(path)

            base["wallet"] = DEFAULT_WALLET
            base["period"] = {
                "from": "2026-09-27T00:00:00",
                "to": "2026-10-03T12:00:00Z",
            }
            path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "period.from.*timezone"):
                load_report_input(path)

    def test_write_report_json_is_deterministic(self) -> None:
        generated_at = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        report = Report(
            schema_version="1.0",
            generated_at=generated_at,
            input_summary={"wallet": DEFAULT_WALLET, "chainIds": [999]},
            days=(),
            transactions=(),
            diagnostics=Diagnostics(warnings=(), reasons=(), rpc_endpoints=()),
        )

        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.json"
            second = Path(temporary) / "second.json"
            write_report_json(report, first)
            write_report_json(replace(report), second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            text = first.read_text(encoding="utf-8")
            self.assertLess(text.index('"days"'), text.index('"diagnostics"'))
            self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
