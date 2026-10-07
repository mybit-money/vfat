from __future__ import annotations

import unittest

from vfat_report.cli import parse_args
from vfat_report.prices import DEFAULT_BASE_URL


class PriceCliTests(unittest.TestCase):
    def test_adapter_override_is_optional_and_keeps_verbatim_value(self) -> None:
        defaults = parse_args(["--input", "input.json"])
        custom = parse_args(["--input", "input.json", "--adapter", "1:Uniswap_V4"])

        self.assertIsNone(defaults.adapter)
        self.assertEqual(custom.adapter, "1:Uniswap_V4")

    def test_price_provider_is_enabled_by_default_and_configurable(self) -> None:
        defaults = parse_args(["--input", "input.json"])
        disabled = parse_args(["--input", "input.json", "--no-prices"])
        custom = parse_args(
            ["--input", "input.json", "--price-api-base", "https://prices.example"]
        )

        self.assertEqual(defaults.price_api_base, DEFAULT_BASE_URL)
        self.assertFalse(defaults.no_prices)
        self.assertTrue(disabled.no_prices)
        self.assertEqual(custom.price_api_base, "https://prices.example")


if __name__ == "__main__":
    unittest.main()
