from __future__ import annotations

import unittest

from vfat_report.adapters.base import AdapterKey, AdapterResolutionError
from vfat_report.adapters.registry import derive_adapter_key, resolve_adapter_key
from vfat_report.contracts import PositionInput


SICKLE = "0x05a34ca31a38c136b8489d4147112cfc4a92a155"


def _position(chain_id: int, protocol_type: str | None = None) -> PositionInput:
    metadata = {"protocolType": protocol_type} if protocol_type is not None else None
    return PositionInput("lineage", chain_id, "nest", "nft", SICKLE, metadata=metadata)


class AdapterRegistryTests(unittest.TestCase):
    def test_adapter_key_parses_and_formats_canonical_protocol_type(self) -> None:
        self.assertEqual(AdapterKey.parse("1:Uniswap_V4"), AdapterKey(1, "uniswap_v4"))
        self.assertEqual(str(AdapterKey(1, "uniswap_v4")), "1:uniswap_v4")

    def test_legacy_nest_inference_requires_only_nest_report_protocol(self) -> None:
        legacy = _position(999)

        self.assertEqual(derive_adapter_key(legacy, ("nest",)), AdapterKey(999, "nest"))
        with self.assertRaises(AdapterResolutionError) as error:
            derive_adapter_key(legacy, ("nest", "other"))
        self.assertEqual(str(error.exception), "adapter_protocol_type_required")

    def test_explicit_ethereum_v4_metadata_selects_adapter_key(self) -> None:
        position = _position(1, "Uniswap_V4")

        self.assertEqual(
            resolve_adapter_key((position,), ("uniswap",)),
            AdapterKey(1, "uniswap_v4"),
        )

    def test_ethereum_without_protocol_type_fails_closed(self) -> None:
        with self.assertRaises(AdapterResolutionError) as error:
            derive_adapter_key(_position(1), ("uniswap",))
        self.assertEqual(str(error.exception), "adapter_protocol_type_required")

    def test_mixed_position_keys_are_rejected(self) -> None:
        with self.assertRaises(AdapterResolutionError) as error:
            resolve_adapter_key((_position(999), _position(1, "uniswap_v4")), ("nest",))
        self.assertEqual(str(error.exception), "mixed_report_adapters_unsupported")

    def test_malformed_override_is_rejected(self) -> None:
        for override in ("uniswap_v4", "abc:uniswap_v4", "1:", "1:uniswap:v4"):
            with self.subTest(override=override):
                with self.assertRaises(AdapterResolutionError) as error:
                    resolve_adapter_key((_position(1, "uniswap_v4"),), ("uniswap",), override)
                self.assertEqual(str(error.exception), "invalid_adapter_override")

    def test_override_must_match_derived_key(self) -> None:
        with self.assertRaises(AdapterResolutionError) as error:
            resolve_adapter_key((_position(1, "uniswap_v4"),), ("uniswap",), "999:nest")
        self.assertEqual(str(error.exception), "adapter_override_mismatch")

    def test_empty_position_set_is_unresolved(self) -> None:
        with self.assertRaises(AdapterResolutionError) as error:
            resolve_adapter_key((), ("nest",))
        self.assertEqual(str(error.exception), "report_adapter_unresolved")


if __name__ == "__main__":
    unittest.main()
