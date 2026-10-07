from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .prices import DEFAULT_BASE_URL
from .runner import run


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a VFAT position report")
    parser.add_argument("--input", required=True, help="Normalized VFAT MCP input JSON")
    parser.add_argument("--output-dir", default="report-output")
    parser.add_argument(
        "--history-root",
        type=Path,
        help="Recursively merge compatible input.json files before building",
    )
    parser.add_argument("--cache-dir", default=".cache/vfat-position-report")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rpc", action="append", default=[])
    parser.add_argument("--adapter", help="Expected adapter as <chain-id>:<protocol-type>")
    parser.add_argument("--price-api-base", default=DEFAULT_BASE_URL)
    parser.add_argument("--no-prices", action="store_true")
    parser.add_argument("--now", help="UTC ISO timestamp for reproducible runs")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return run(parse_args(argv))
