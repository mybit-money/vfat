from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from vfat_report.cli import main
from vfat_report.contracts import NormalizedTransaction, PositionInput, TokenAmount
from vfat_report.events import load_chain_profile
from vfat_report.runner import _select_reward_tokens, profile_for_positions


FIXTURES = Path(__file__).parent / "fixtures"
NEST = "0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035"
DRV = "0x9628bba16db41ea7fe1fd84f9ce53bc27c63f59b"


class FailingRpcClient:
    def __init__(self, _endpoints) -> None:
        pass

    def get_receipt(self, _tx_hash: str):
        raise RuntimeError("all RPC endpoints failed")


class RunnerProfileTests(unittest.TestCase):
    def test_tracked_sickles_come_from_current_positions(self) -> None:
        profile_path = Path(__file__).parents[1] / "profiles" / "hyperevm-nest.json"
        profile = load_chain_profile(profile_path)
        other_sickle = "0x1111111111111111111111111111111111111111"
        position = PositionInput(
            position_id="manager:1",
            chain_id=999,
            protocol="nest",
            position_type="nft",
            sickle_address=other_sickle,
        )

        actual = profile_for_positions(profile, (position,))

        self.assertEqual(actual.tracked_sickle_addresses, frozenset({other_sickle}))
        self.assertEqual(
            replace(actual, tracked_sickle_addresses=profile.tracked_sickle_addresses),
            profile,
        )

    def test_run_survives_rpc_failure_and_excludes_unsupported_chains(self) -> None:
        tx_hash = "0x" + "ab" * 32
        payload = json.loads((FIXTURES / "minimal-input.json").read_text(encoding="utf-8"))
        payload["period"] = {"from": "2026-10-02T00:00:00Z", "to": "2026-10-03T00:00:00Z"}
        payload["filters"]["chainIds"] = [999, 8453]
        payload["positions"].append(
            {
                "positionId": "base:1",
                "chainId": 8453,
                "protocol": "nest",
                "positionType": "nft",
                "sickleAddress": "0x1111111111111111111111111111111111111111",
            }
        )
        payload["capitalPoints"] = [
            {"positionId": "nft:91811", "timestamp": "2026-10-01T00:00:00Z", "currentBalanceUsd": "1000"},
            {"positionId": "base:1", "timestamp": "2026-10-01T00:00:00Z", "currentBalanceUsd": "5000"},
        ]
        payload["activities"] = [
            {
                "chainId": 999,
                "transactionHash": tx_hash,
                "timestamp": "2026-10-02T06:00:00Z",
                "actionType": "compounded",
                "sourcePositionIds": ["nft:91811"],
                "recipientPositionId": "nft:91811",
            }
        ]

        with tempfile.TemporaryDirectory() as temporary, patch(
            "vfat_report.runner.JsonRpcClient", FailingRpcClient
        ):
            root = Path(temporary)
            (root / "input.json").write_text(json.dumps(payload), encoding="utf-8")
            exit_code = main(
                [
                    "--input", str(root / "input.json"),
                    "--output-dir", str(root / "out"),
                    "--cache-dir", str(root / "cache"),
                    "--now", "2026-10-03T12:00:00Z",
                    "--no-prices",
                ]
            )
            report = json.loads((root / "out" / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        warnings = report["diagnostics"]["warnings"]
        self.assertIn(f"receipt_fetch_failed:{tx_hash}", warnings)
        self.assertIn("chain_unsupported:8453", warnings)
        self.assertEqual(Decimal(report["days"][0]["average_capital_usd"]), Decimal("1000"))

    def test_reward_token_filter_drops_claims_of_other_tokens(self) -> None:
        def claim(tx_hash: str, token: str) -> NormalizedTransaction:
            return NormalizedTransaction(
                chain_id=999,
                transaction_hash=tx_hash,
                timestamp=datetime(2026, 10, 2, tzinfo=timezone.utc),
                action_type="compounded",
                gross_claims=(TokenAmount(token, None, 18, 10**18),),
            )

        selected = _select_reward_tokens(
            [claim("0x" + "01" * 32, NEST), claim("0x" + "02" * 32, DRV)], frozenset({NEST})
        )

        self.assertEqual([item.transaction_hash for item in selected], ["0x" + "01" * 32])


if __name__ == "__main__":
    unittest.main()
