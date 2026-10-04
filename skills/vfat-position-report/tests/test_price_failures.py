from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from vfat_report.prices import DefiLlamaPriceClient


NEST = "0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035"


class PriceFailureTests(unittest.TestCase):
    def test_provider_failure_returns_no_quotes_and_diagnostic(self) -> None:
        def transport(_url: str):
            raise OSError("temporary failure")

        client = DefiLlamaPriceClient(transport=transport)

        quotes = client.get_quotes(
            ((NEST, datetime(2026, 10, 3, tzinfo=timezone.utc)),), chain_id=999
        )

        self.assertEqual(quotes, {})
        self.assertIn("price_provider_failed", client.diagnostics[0])

    def test_requests_are_split_into_at_most_fifty_points(self) -> None:
        calls: list[str] = []

        def transport(url: str):
            calls.append(url)
            return {"coins": {}}

        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        requests = tuple((NEST, start + timedelta(minutes=index)) for index in range(51))
        client = DefiLlamaPriceClient(transport=transport)

        client.get_quotes(requests, chain_id=999)

        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
