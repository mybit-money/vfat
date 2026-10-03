---
name: vfat-position-report
description: Build a reproducible daily report for VFAT positions, NEST claims and compounds, realized APR, automation fees, gas-account charges, and the aggregate capital/APR chart. Use for wallet position reports, compound reconciliation, or VFAT activity analysis.
---

# VFAT Position Report

Use VFAT MCP for every VFAT discovery and data request. The bundled Python code may read public chain receipts through RPC, but must never call or scrape VFAT HTTP endpoints.

## Defaults

- Wallet: `0x330d2a845d2df4e329034d72719c7c53f9c1f87a`
- Period: seven UTC calendar days, including the current partial day
- Scope: every NEST position, initially HyperEVM (`chainId` 999)
- Output: daily rows newest first plus a capital/APR chart

Override any default the user states explicitly.

## Workflow

1. Discover all wallet positions with `mcp__vfat__get_position_performance` before requesting detail.
2. Keep every position matching the requested network, protocol, and reward filters. Do not assume one fixed compound recipient: a transaction may source or fund several positions, and the recipient may change.
3. For each relevant position, request hourly capital history with `mcp__vfat__get_position_performance_history` and activity with `mcp__vfat__get_position_activity` for the UTC period.
4. Normalize MCP results into the input contract in [references/data-contract.md](references/data-contract.md). Preserve source metadata, include every position, and deduplicate activities only by `(chainId, transactionHash)`.
5. Run:

   `python scripts/vfat_position_report.py --input <normalized.json> --output-dir <output>`

6. Inspect `report.json` diagnostics before presenting `report.html`. State any missing valuation, insufficient capital coverage, unavailable receipt, or unsupported chain clearly; never replace an unknown amount with zero.

Use [references/calculation-rules.md](references/calculation-rules.md) when explaining or reconciling numbers. The longer operator guide is at `docs/vfat-position-report.md` in the project that ships this skill.

## Interpretation guardrails

- Daily boundaries are UTC. Current-day APR is prorated by elapsed UTC time.
- Claims are the aggregate across all selected positions; transaction counts are unique on-chain transactions.
- Automation fee is decoded from token transfers and compared with the expected 1.8%, not fabricated from that percentage.
- A gas-account debit and network gas are separate costs. Attribute only a confirmed gas-account debit to portfolio APR; show network gas separately.
- Capital uses time-weighted last-observation-carried-forward history. Below 75% daily coverage, capital and APR are unreliable.
- Missing historical USD prices leave USD totals and APR null with a reason. Token-native amounts remain available.
- Transaction data is unsigned. Never ask for keys, sign, or claim to broadcast a transaction.

Version 1 supports on-chain decoding for the bundled HyperEVM/NEST profile. Other chains remain discoverable through VFAT MCP but require a reviewed chain profile before decoding.
