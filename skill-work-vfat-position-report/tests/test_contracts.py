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
        self.assertIsNone(report_input.positions[0].position_root_token_id)
        self.assertEqual(report_input.positions[0].token_id, "91811")

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

    def test_loads_ethereum_v4_lineage_without_replacing_current_token_id(self) -> None:
        payload = json.loads((FIXTURES / "minimal-input.json").read_text(encoding="utf-8"))
        root = "bd216513d74c8cf14cf4747e6aaa6420ff64ee9e:413470"
        pool_id = "0x20ae5557f7d6ce39a6e5370c331106a87a80ea5c1bec686361bde2d9f5e82631"
        metadata = {
            "protocolType": "uniswap_v4",
            "poolId": pool_id,
            "poolManagerAddress": "0x000000000004444c5dc75cb358380d2e3de08a90",
        }
        payload["filters"] = {"chainIds": [1], "protocols": ["uniswap"]}
        payload["positions"][0].update(
            positionId=root,
            chainId=1,
            protocol="uniswap",
            tokenId="413473",
            positionRootTokenId=root,
            metadata=metadata,
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ethereum.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            position = load_report_input(path).positions[0]

        self.assertEqual(position.position_id, root)
        self.assertEqual(position.position_root_token_id, root)
        self.assertEqual(position.token_id, "413473")
        self.assertEqual(position.metadata, metadata)
        self.assertEqual(position.metadata["protocolType"], "uniswap_v4")
        self.assertEqual(position.metadata["poolId"], pool_id)

    def test_history_does_not_merge_different_lineage_or_protocol_metadata(self) -> None:
        primary = json.loads((FIXTURES / "minimal-input.json").read_text(encoding="utf-8"))
        primary["positions"][0]["positionRootTokenId"] = "manager:413470"
        primary["positions"][0]["metadata"] = {
            "protocolType": "uniswap_v4",
            "poolId": "0x" + "a" * 64,
            "poolManagerAddress": "0x000000000004444c5dc75cb358380d2e3de08a90",
        }
        primary["period"] = {
            "from": "2026-10-02T00:00:00Z",
            "to": "2026-10-03T00:00:00Z",
        }
        old = json.loads(json.dumps(primary))
        old["period"]["from"] = "2026-09-01T00:00:00Z"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "current"
            history = root / "history"
            current.mkdir()
            history.mkdir()
            path = current / "input.json"
            path.write_text(json.dumps(primary), encoding="utf-8")
            old_path = history / "input.json"

            for field, replacement in (
                ("positionRootTokenId", "manager:413469"),
                ("protocolType", "other"),
                ("poolId", "0x" + "b" * 64),
                ("poolManagerAddress", "0x" + "1" * 40),
            ):
                candidate = json.loads(json.dumps(old))
                target = candidate["positions"][0]
                if field == "positionRootTokenId":
                    target[field] = replacement
                else:
                    target["metadata"][field] = replacement
                old_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.subTest(field=field):
                    self.assertEqual(
                        load_report_input(path, history_root=root).start.isoformat(),
                        "2026-10-02T00:00:00+00:00",
                    )

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
