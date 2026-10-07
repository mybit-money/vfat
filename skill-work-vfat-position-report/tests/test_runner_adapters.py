"""Runner adapter selection and fail-closed orchestration tests."""

from __future__ import annotations

import json
import copy
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from vfat_report.adapters.base import AdapterResolutionError
from vfat_report.cli import parse_args
from vfat_report.contracts import ActivityInput, CapitalPoint, PositionInput, ReportInput
from vfat_report import runner
from vfat_report.prices import PriceQuote


UTC = timezone.utc
START = datetime(2026, 10, 2, tzinfo=UTC)
END = datetime(2026, 10, 3, tzinfo=UTC)
SICKLE = "0x05a34ca31a38c136b8489d4147112cfc4a92a155"
ETH_SICKLE = "0xfb12aa1f51ba66ef761def09233946a4369b0de6"
ETH_MANAGER = "0xbd216513d74c8cf14cf4747e6aaa6420ff64ee9e"
POOL_MANAGER = "0x000000000004444c5dc75cb358380d2e3de08a90"
POOL_ID = "0x20ae5557f7d6ce39a6e5370c331106a87a80ea5c1bec686361bde2d9f5e82631"
ETH = "0x0000000000000000000000000000000000000000"
DRV = "0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be"
ROOT = "bd216513d74c8cf14cf4747e6aaa6420ff64ee9e:413470"
FIXTURES = Path(__file__).parent / "fixtures" / "ethereum-uniswap-v4"


def nest_position() -> PositionInput:
    return PositionInput("nest:1", 999, "nest", "nft", SICKLE)


def ethereum_position() -> PositionInput:
    return PositionInput(
        ROOT, 1, "uniswap", "nft", ETH_SICKLE,
        token_id="413473", nft_manager_address=ETH_MANAGER,
        position_root_token_id=ROOT,
        metadata={
            "protocolType": "uniswap_v4", "poolAddress": POOL_MANAGER,
            "poolManagerAddress": POOL_MANAGER, "poolId": POOL_ID,
            "underlying": [
                {"address": ETH, "symbol": "ETH", "decimals": 18},
                {"address": DRV, "symbol": "DRV", "decimals": 18},
            ],
        },
    )


def report_input(position: PositionInput, receipt_name: str | None = None) -> ReportInput:
    if receipt_name:
        receipt = json.loads((FIXTURES / f"{receipt_name}-receipt.json").read_text())
        tx_hash = receipt["transactionHash"]
    else:
        tx_hash = "0x" + "12" * 32
    activity = ActivityInput(
        position.chain_id, tx_hash, START.replace(hour=12), "compound",
        (position.position_id,), position.position_id,
    )
    return ReportInput(
        "1.0", "0x330d2a845d2df4e329034d72719c7c53f9c1f87a",
        START, END, (position.chain_id,), (position.protocol,), (),
        (position,), (activity,),
        (
            CapitalPoint(position.position_id, START, Decimal("1000"), Decimal("10")),
            CapitalPoint(position.position_id, END, Decimal("1000"), Decimal("15")),
        ),
        {},
    )


class RunnerAdapterTests(unittest.TestCase):
    def run_input(
        self, data: ReportInput, *, receipt: dict | None = None,
        extra_args: tuple[str, ...] = (), rpc_factory=None,
        prices: bool = False, price_factory=None,
    ) -> tuple[dict, list[tuple[str, ...]]]:
        endpoints: list[tuple[str, ...]] = []

        def make_rpc(urls):
            endpoints.append(tuple(urls))
            if rpc_factory is not None:
                return rpc_factory(urls)
            return type("Rpc", (), {"get_receipt": lambda self, hash: receipt})()

        with tempfile.TemporaryDirectory() as temporary:
            args = parse_args([
                "--input", "unused.json", "--output-dir", str(Path(temporary) / "out"),
                "--cache-dir", str(Path(temporary) / "cache"),
                *(() if prices else ("--no-prices",)),
                *extra_args,
            ])
            with patch.object(runner, "load_report_input", return_value=data), patch.object(
                runner, "JsonRpcClient", side_effect=make_rpc
            ), patch.object(
                runner, "DefiLlamaPriceClient", side_effect=price_factory
            ):
                self.assertEqual(runner.run(args), 0)
            output = json.loads((Path(temporary) / "out" / "report.json").read_text())
        return output, endpoints

    def test_nest_is_selected_automatically_and_uses_its_rpc_defaults(self) -> None:
        data = report_input(nest_position())
        receipt = {"transactionHash": data.activities[0].transaction_hash, "logs": []}

        output, endpoints = self.run_input(data, receipt=receipt)

        self.assertEqual(endpoints, [(
            "https://rpc.hyperliquid.xyz/evm", "https://rpc.hypurrscan.io"
        )])
        self.assertEqual(output["transactions"][0]["chain_id"], 999)

    def test_ethereum_is_selected_automatically_with_its_decoder_and_defaults(self) -> None:
        data = report_input(ethereum_position(), "manual-compound")
        receipt = json.loads((FIXTURES / "manual-compound-receipt.json").read_text())

        output, endpoints = self.run_input(data, receipt=receipt)

        self.assertEqual(endpoints, [(
            "https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com"
        )])
        self.assertEqual(output["transactions"][0]["chain_id"], 1)
        self.assertEqual(output["transactions"][0]["gross_claims"][0]["token_address"], DRV)

    def test_matching_override_and_user_rpc_take_precedence(self) -> None:
        data = report_input(nest_position())
        receipt = {"transactionHash": data.activities[0].transaction_hash, "logs": []}

        output, endpoints = self.run_input(
            data, receipt=receipt,
            extra_args=("--adapter", "999:nest", "--rpc", "https://custom.example"),
        )

        self.assertEqual(endpoints, [("https://custom.example",)])
        self.assertEqual(output["diagnostics"]["rpc_endpoints"], ["https://custom.example"])

    def test_override_mismatch_fails_before_rpc(self) -> None:
        data = report_input(nest_position())
        with self.assertRaisesRegex(AdapterResolutionError, "adapter_override_mismatch"):
            self.run_input(data, extra_args=("--adapter", "1:uniswap_v4"),
                           rpc_factory=lambda urls: self.fail("RPC constructed"))

    def test_mixed_positions_fail_before_rpc(self) -> None:
        nest = report_input(nest_position())
        mixed = replace(nest, positions=(nest_position(), ethereum_position()))
        with self.assertRaisesRegex(AdapterResolutionError, "mixed_report_adapters_unsupported"):
            self.run_input(mixed, rpc_factory=lambda urls: self.fail("RPC constructed"))

    def test_foreign_chain_activity_fails_before_rpc(self) -> None:
        data = report_input(nest_position())
        foreign = replace(
            data, activities=(replace(data.activities[0], chain_id=1),)
        )
        with self.assertRaisesRegex(AdapterResolutionError, "activity_chain_mismatch"):
            self.run_input(
                foreign, rpc_factory=lambda urls: self.fail("RPC constructed")
            )

    def test_unsupported_adapter_retains_capital_and_pnl_without_rpc(self) -> None:
        base = nest_position()
        unsupported = replace(
            base, chain_id=8453, protocol="aerodrome",
            metadata={"protocolType": "aerodrome"},
        )
        data = report_input(unsupported)

        output, endpoints = self.run_input(
            data, rpc_factory=lambda urls: self.fail("RPC constructed")
        )

        self.assertEqual(endpoints, [])
        self.assertEqual(len(output["transactions"]), 1)
        tx = output["transactions"][0]
        self.assertEqual(tx["transaction_hash"], data.activities[0].transaction_hash)
        for field in (
            "gross_claim_usd", "net_compound_usd", "automation_fee_usd",
            "gas_account_debit_usd",
        ):
            self.assertIsNone(tx[field]["usd"])
            self.assertEqual(tx[field]["reason"], "chain_protocol_unsupported")
        day = output["days"][0]
        for field in (
            "gross_claim_usd", "net_compound_usd", "automation_fee_usd",
            "realized_apr_percent",
        ):
            self.assertIsNone(day[field])
        self.assertIsNotNone(day["average_capital_usd"])
        self.assertIsNotNone(day["cumulative_pnl_usd"])
        self.assertIn("chain_protocol_unsupported", day["reasons"])
        self.assertIn("chain_protocol_unsupported", output["diagnostics"]["reasons"])

    def test_missing_receipt_retains_one_unavailable_transaction(self) -> None:
        data = report_input(nest_position())

        output, endpoints = self.run_input(data, receipt=None)

        self.assertEqual(len(endpoints), 1)
        self.assertEqual(len(output["transactions"]), 1)
        tx = output["transactions"][0]
        self.assertEqual(tx["transaction_hash"], data.activities[0].transaction_hash)
        self.assertEqual(tx["source_position_ids"], ["nest:1"])
        for field in (
            "gross_claim_usd", "net_compound_usd", "automation_fee_usd",
            "gas_account_debit_usd",
        ):
            self.assertIsNone(tx[field]["usd"])
            self.assertEqual(tx[field]["reason"], "receipt_unavailable")
        day = output["days"][0]
        self.assertIsNone(day["gross_claim_usd"])
        self.assertIsNone(day["net_compound_usd"])
        self.assertIsNone(day["automation_fee_usd"])
        self.assertIsNone(day["realized_apr_percent"])
        self.assertIn("receipt_unavailable", day["reasons"])
        self.assertIn(
            f"receipt_unavailable:{data.activities[0].transaction_hash}",
            output["diagnostics"]["warnings"],
        )

    def test_known_adapter_rejects_unsupported_position_before_rpc(self) -> None:
        position = replace(ethereum_position(), sickle_address=ETH)
        with self.assertRaisesRegex(AdapterResolutionError, "adapter_position_unsupported"):
            self.run_input(
                report_input(position),
                rpc_factory=lambda urls: self.fail("RPC constructed"),
            )

    def test_ethereum_pricing_uses_chain_slug_and_preserves_partial_claim_and_fee(self) -> None:
        data = report_input(ethereum_position(), "manual-compound")
        receipt = json.loads((FIXTURES / "manual-compound-receipt.json").read_text())
        price_calls = []

        class PriceClient:
            diagnostics = []

            def get_quotes(self, requests, *, chain_slug):
                points = tuple(requests)
                price_calls.append((chain_slug, points))
                return {
                    (address, int(timestamp.timestamp())):
                    PriceQuote(address, int(timestamp.timestamp()),
                               int(timestamp.timestamp()), Decimal("1"), None, "fixture")
                    for address, timestamp in points
                }

        output, _ = self.run_input(
            data, receipt=receipt, prices=True,
            price_factory=lambda **kwargs: PriceClient(),
        )

        tx = output["transactions"][0]
        self.assertEqual(price_calls[0][0], "ethereum")
        self.assertIn(
            "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            {address for address, _ in price_calls[0][1]},
        )
        self.assertIsNone(tx["gross_claim_usd"]["usd"])
        self.assertEqual(tx["gross_claim_usd"]["reason"], "native_claim_unavailable")
        self.assertIsNone(tx["automation_fee_usd"]["usd"])
        self.assertEqual(tx["automation_fee_usd"]["reason"], "native_fee_unavailable")
        self.assertIsNone(output["days"][0]["gross_claim_usd"])
        self.assertIsNone(output["days"][0]["automation_fee_usd"])
        self.assertIsNone(output["days"][0]["realized_apr_percent"])
        self.assertIn("native_claim_unavailable", output["days"][0]["reasons"])
        self.assertIn("native_fee_unavailable", output["days"][0]["reasons"])

    def test_rebalance_principal_separation_survives_pricing(self) -> None:
        data = report_input(ethereum_position(), "rebalance-413470-413473")
        receipt = json.loads(
            (FIXTURES / "rebalance-413470-413473-receipt.json").read_text()
        )

        class PriceClient:
            diagnostics = []

            def get_quotes(self, requests, *, chain_slug):
                return {
                    (address, int(timestamp.timestamp())):
                    PriceQuote(address, int(timestamp.timestamp()),
                               int(timestamp.timestamp()), Decimal("1"), None, "fixture")
                    for address, timestamp in requests
                }

        output, _ = self.run_input(
            data, receipt=receipt, prices=True,
            price_factory=lambda **kwargs: PriceClient(),
        )

        tx = output["transactions"][0]
        self.assertIsNone(tx["gross_claim_usd"]["usd"])
        self.assertEqual(
            tx["gross_claim_usd"]["reason"], "claim_principal_separation_unavailable"
        )
        self.assertIsNone(tx["net_compound_usd"]["usd"])
        self.assertEqual(
            tx["net_compound_usd"]["reason"], "claim_principal_separation_unavailable"
        )
        self.assertIsNone(output["days"][0]["realized_apr_percent"])

    def test_ambiguous_fee_receipt_becomes_unavailable_transaction(self) -> None:
        data = report_input(ethereum_position(), "manual-compound")
        receipt = json.loads((FIXTURES / "manual-compound-receipt.json").read_text())
        operation = copy.deepcopy(receipt["logs"][0])
        operation["topics"][1] = "0x" + "11" * 32
        operation["logIndex"] = "0x1000"
        fee = copy.deepcopy(next(
            log for log in receipt["logs"]
            if len(log["topics"]) == 3
            and log["topics"][2].endswith("d4627ecb405b64448ee6b07dcf860bf55590c83d")
        ))
        fee["logIndex"] = "0x1001"
        receipt["logs"].extend((operation, fee))

        output, _ = self.run_input(data, receipt=receipt)

        self.assertEqual(len(output["transactions"]), 1)
        tx = output["transactions"][0]
        self.assertEqual(tx["automation_fee_usd"]["reason"], "fee_attribution_ambiguous")
        self.assertIsNone(tx["automation_fee_usd"]["usd"])
        self.assertIn("fee_attribution_ambiguous", output["days"][0]["reasons"])

    def test_unknown_claim_token_stays_raw_and_unpriced(self) -> None:
        data = report_input(ethereum_position(), "manual-compound")
        receipt = json.loads((FIXTURES / "manual-compound-receipt.json").read_text())
        for log in receipt["logs"]:
            log["logIndex"] = hex(int(log["logIndex"], 16) * 2)
        unknown = copy.deepcopy(receipt["logs"][1])
        unknown["address"] = "0x" + "ab" * 20
        unknown["logIndex"] = hex(int(unknown["logIndex"], 16) + 1)
        receipt["logs"].append(unknown)

        class PriceClient:
            diagnostics = []

            def get_quotes(self, requests, *, chain_slug):
                return {
                    (address, int(timestamp.timestamp())):
                    PriceQuote(address, int(timestamp.timestamp()),
                               int(timestamp.timestamp()), Decimal("1"), None, "fixture")
                    for address, timestamp in requests
                }

        output, _ = self.run_input(
            data, receipt=receipt, prices=True,
            price_factory=lambda **kwargs: PriceClient(),
        )

        tx = output["transactions"][0]
        raw = next(
            amount["raw_amount"] for amount in tx["gross_claims"]
            if amount["token_address"] == "0x" + "ab" * 20
        )
        self.assertEqual(raw, 149900950242857240585)
        self.assertIsNone(tx["gross_claim_usd"]["usd"])
        self.assertIsNone(output["days"][0]["realized_apr_percent"])
        self.assertIn("unknown_token_decimals", output["days"][0]["reasons"])
        self.assertIn(
            "unknown_token_decimals:0x" + "ab" * 20, tx["warnings"]
        )


if __name__ == "__main__":
    unittest.main()
