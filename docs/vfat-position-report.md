# VFAT position report: operator guide

This project builds a reproducible daily report for a wallet's VFAT/NEST positions. VFAT MCP supplies discovery, position history, and activity; the local Python runner decodes public receipts, caches immutable data, calculates daily aggregates, and creates a standalone HTML report.

## Quick start

1. Ask VFAT MCP for all positions using `mcp__vfat__get_position_performance` and the wallet address.
2. For each position in scope, request hourly history with `mcp__vfat__get_position_performance_history` and activity with `mcp__vfat__get_position_activity`.
3. Convert the results to `skills/vfat-position-report/references/data-contract.md` and save them as `input.json`.
4. Run from the skill directory:

   `python scripts/vfat_position_report.py --input input.json --output-dir output`

5. Review `output/report.json`, especially diagnostics and reason codes, then open `output/report.html`.

Defaults are wallet `0x330d2a845d2df4e329034d72719c7c53f9c1f87a`, seven UTC calendar days including today, all NEST positions, and HyperEVM. Command-line `--now` makes a run reproducible; `--refresh` refetches receipts that are eligible for refresh, while immutable receipt cache entries are reused.

## MCP collection sequence

Discover first. Never call VFAT APIs from the Python runner or scrape the VFAT site.

- `get_position_performance`: obtain the complete wallet position set and current identity fields.
- `get_position_performance_history`: request the report period at hourly granularity for each position/lineage.
- `get_position_activity`: request the same period for every relevant NFT position using chain, Sickle, manager, and token ID from discovery.

Normalize timestamps to UTC, keep stable position IDs, and preserve all activity records until transaction deduplication. A compound recipient is not a global setting: infer and store it per transaction when VFAT exposes it. Retain closed positions that overlap the reporting window.

## Outputs

The daily table is newest first. Its leading economic fields are average capital, gross claims, and realized APR. It also exposes net compound, the observed automation fee, gas-account debit, claim transaction count, coverage, and reason codes.

The HTML chart uses aggregate capital in USDT/USD terms on the first axis and realized APR on the second. Missing values create a visible break rather than a fabricated zero. The first incomplete capital point is naturally excluded when it does not meet coverage requirements.

Transaction detail remains in JSON for on-demand reconciliation: source and recipient positions, native token amounts, effective automation fee ratio, gas-account debit, network gas, and valuation provenance.

## Cache and RPC behavior

The runner keeps immutable receipts and report snapshots under the selected cache directory, writes updates atomically, quarantines corrupt files, and briefly caches missing receipts. The public RPC client enforces a rolling 100-request-per-minute ceiling and tries the configured backup endpoint after retryable failures. The most recent three UTC days may be refreshed; older completed days are reusable.

Version 1 decodes HyperEVM/NEST using `profiles/hyperevm-nest.json`. Adding a network requires verified contract addresses, event signatures, token metadata, pool mapping, real reduced receipt fixtures, and regression tests. Discovery through VFAT MCP alone does not make another chain safe to decode.

## Missing data and reconciliation

Unknown historical USD prices stay `null`; token-native quantities remain visible. Capital coverage below 75%, missing receipts, fee deviations, and absent gas-account events are surfaced as diagnostics. Network gas and a gas-account debit are never merged automatically.

For a disagreement with a VFAT CSV, compare unique transaction hashes first, then UTC boundaries, gross token transfers, fee transfers, LP mint amounts, and finally price provenance. CSV is an optional reconciliation source, not the primary input in version 1.

## Handoff to mybit-folio

Use the normalized input and `report.json` as stable adapter boundaries. A TypeScript service can persist all raw MCP activities, receipt logs, decoded transactions, valuations, and daily snapshots in a database while keeping the same calculation rules. Golden JSON fixtures should be shared between Python and TypeScript implementations to detect semantic drift.
