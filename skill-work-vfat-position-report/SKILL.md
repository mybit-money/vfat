---
name: vfat-position-report
description: Use when building a reproducible daily VFAT position report, reconciling NEST claims and compounds, calculating realized APR and automation costs, or charting aggregate capital and APR.
---

# VFAT Position Report

Use VFAT MCP for every VFAT discovery and data request. The bundled Python code may read public chain receipts through RPC, but must never call or scrape VFAT HTTP endpoints.

## Defaults

- Wallet: `0x330d2a845d2df4e329034d72719c7c53f9c1f87a`
- Period: seven UTC calendar days, including the current partial day
- Scope: every NEST position, initially HyperEVM (`chainId` 999)
- Output: daily rows newest first plus interactive capital/APR, portfolio result, and net-claim charts

Override any default the user states explicitly.

## Workflow

1. Discover all wallet positions with `mcp__vfat__get_position_performance` before requesting detail.
2. Keep every position matching the requested network, protocol, and reward filters. Do not assume one fixed compound recipient: a transaction may source or fund several positions, and the recipient may change.
3. For each relevant position, request hourly capital/PnL history with `mcp__vfat__get_position_performance_history` from one hour before the UTC period (the PnL baseline) through the period end, and activity with `mcp__vfat__get_position_activity` for the UTC period. Resolve each unique pool through VFAT MCP and include its address plus both underlying token addresses, symbols, and decimals in position metadata. Use bounded concurrency; on HTTP 429, retry sequentially with a short backoff.
4. Normalize `currentBalanceUsd` and `totalPnlUsd` from every history point into the input contract in [references/data-contract.md](references/data-contract.md). Populate `activeFrom` from the verified opening activity when available; do not invent it. Preserve source metadata, include every position, and deduplicate activities only by `(chainId, transactionHash)`.
5. Run:

   `python scripts/vfat_position_report.py --input <normalized.json> --output-dir <output>`

   When updating from previously saved normalized reports, add `--history-root <reports-directory>`. The runner recursively merges only compatible `input.json` files (same schema, wallet, chains, protocols, and reward-token filters), preserves the earliest period, prefers the primary input for duplicate capital points, and unions duplicate transaction sources. Do not treat the receipt/price cache as VFAT performance history; only normalized inputs preserve that history.

6. The runner values transaction-time amounts through the free DefiLlama historical endpoint by default and caches accepted quotes. Use [references/price-sources.md](references/price-sources.md) for provider rules and failure behavior.
7. Inspect `report.json` diagnostics before presenting `report.html`. State any missing valuation, insufficient capital coverage, unavailable receipt, or unsupported chain clearly; never replace an unknown amount with zero.

Use [references/calculation-rules.md](references/calculation-rules.md) when explaining or reconciling numbers. The longer operator guide is at `docs/vfat-position-report.md` in the project that ships this skill.

## Interpretation guardrails

- Daily boundaries are UTC. Current-day APR is prorated by elapsed UTC time.
- Claims are the aggregate across all selected positions; transaction counts are unique on-chain transactions.
- Automation fee is decoded from token transfers and compared with the expected 1.8%, not fabricated from that percentage.
- A gas-account debit and network gas are separate costs. Attribute only a confirmed gas-account debit to portfolio APR; show network gas separately.
- Capital uses time-weighted last-observation-carried-forward history. Daily position-value change is the raw close-to-close change and therefore includes deposits, withdrawals, compounds, and market movement.
- Cumulative PnL uses VFAT `totalPnlUsd`; daily economic PnL is its change from the prior UTC close and must not add claims or compounds again. A verified new position may use a synthetic `PnL = 0` point at `activeFrom` and interpolate to its first VFAT point; backfill its opening value from that first point. Mark every affected value as estimated. Without verified `activeFrom`, leave the value unavailable.
- Net claim is `gross claim - automation fee - confirmed gas-account debit`. It is a separate cash-flow metric; average net claim includes completed zero-claim UTC days.
- Below 75% daily capital coverage, capital and APR are unreliable.
- Historical quotes must be within 15 minutes of the transaction. Missing or stale prices leave USD totals and APR null with a reason; token-native amounts remain available.
- Transaction data is unsigned. Never ask for keys, sign, or claim to broadcast a transaction.

Version 1.1 supports on-chain decoding for the bundled HyperEVM/NEST profile. Other chains remain discoverable through VFAT MCP but require a reviewed chain profile before decoding.
