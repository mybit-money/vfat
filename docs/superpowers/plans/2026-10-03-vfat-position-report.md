# VFAT Position Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and install a portable Codex skill that uses VFAT MCP input plus HyperEVM receipts to produce cached UTC daily claim/compound aggregates, realized net APR, JSON detail, and a standalone interactive HTML report.

**Architecture:** Keep a version-controlled canonical skill under `skills/vfat-position-report/`, then install the verified package into the personal Codex skills directory. Codex owns VFAT MCP orchestration and writes a versioned input JSON; a dependency-free Python 3.11+ engine owns RPC reads, normalization, caching, aggregation, and HTML generation.

**Tech Stack:** Python 3.11+ standard library, `unittest`, JSON-RPC over `urllib`, HTML/SVG/vanilla JavaScript, Codex `SKILL.md`, VFAT MCP.

**Spec:** `docs/superpowers/specs/2026-10-03-vfat-position-report-design.md`

## Global Constraints

- Use `mcp__vfat__*` for all VFAT discovery, history, analytics, and attribution; never scrape VFAT or call its HTTP API from Python.
- Default wallet is `0x330d2a845d2df4e329034d72719c7c53f9c1f87a`.
- Default report window is seven UTC days including the current day.
- V1 onchain decoding supports HyperEVM chain ID `999` and NEST positions.
- Use only the Python standard library at runtime; the generated HTML must not use a CDN.
- Preserve every unavailable value as `null` plus a reason; never silently replace unavailable data with zero.
- Refresh the current UTC day and two preceding completed days; reuse older compatible cache entries unless `--refresh` is supplied.
- Do not add a database or autonomous MCP client to the Python package.
- Source code and tests live in the repository; installation to `C:\Users\petri\.codex\skills\vfat-position-report\` happens only after verification.

## Review Focus

- The same compound transaction appears in several position histories: count it once while retaining every source position; pinned by `test_merge_activity_deduplicates_transaction_and_sources` in Task 3.
- Hourly capital has gaps or starts mid-day: compute time coverage exactly and return no APR below 75%; pinned by `test_time_weighted_capital_reports_gap_and_threshold` in Task 2.
- A reward or cost lacks historical USD valuation: retain token amounts and set dependent USD/APR fields to null with reasons; pinned by `test_daily_aggregate_propagates_missing_usd` in Task 5.
- A receipt contains an unknown fee or gas-account event: do not infer a user cost from the advertised 1.8% or keeper gas; pinned by `test_unknown_cost_event_is_unavailable_not_zero` in Task 3.
- Cache files are corrupt or use another schema/calculation version: refetch or recompute only the affected layer without discarding valid immutable receipts; pinned by `test_cache_invalidates_derived_layer_only` in Task 4.

---

## File Structure

```text
skills/vfat-position-report/
  SKILL.md                         Codex orchestration and user-facing defaults
  scripts/vfat_position_report.py Thin executable entry point
  scripts/vfat_report/
    __init__.py                    Public version constants
    contracts.py                   Input/output dataclasses and JSON validation
    capital.py                     Hourly coverage and time-weighted capital
    events.py                      ERC-20/Mint/cost log decoding and tx merging
    rpc.py                         Rate-limited retrying JSON-RPC reader
    cache.py                       Versioned three-layer filesystem cache
    aggregate.py                   UTC buckets, costs, and realized APR
    html_report.py                 Standalone SVG/JS report rendering
    cli.py                         Command-line coordination and diagnostics
  profiles/hyperevm-nest.json      Addresses, topics, RPC defaults, token metadata
  references/data-contract.md      Neutral MCP input and report JSON contracts
  references/calculation-rules.md  Capital, fee, cost, coverage, and APR formulas
  tests/
    fixtures/                      Deterministic MCP inputs and receipts
    test_contracts.py
    test_capital.py
    test_events.py
    test_cache_rpc.py
    test_aggregate.py
    test_html_cli.py
docs/vfat-position-report.md        Project operator guide
.gitignore                          Generated cache/report directories
```

## Task 1: Versioned Contracts and CLI Skeleton

**Files:**
- Create: `skills/vfat-position-report/scripts/vfat_report/__init__.py`
- Create: `skills/vfat-position-report/scripts/vfat_report/contracts.py`
- Create: `skills/vfat-position-report/scripts/vfat_report/cli.py`
- Create: `skills/vfat-position-report/scripts/vfat_position_report.py`
- Create: `skills/vfat-position-report/tests/fixtures/minimal-input.json`
- Create: `skills/vfat-position-report/tests/test_contracts.py`

**Interfaces:**
- Produces: `load_report_input(path: Path) -> ReportInput`
- Produces: `write_report_json(report: Report, path: Path) -> None`
- Produces: `parse_args(argv: Sequence[str]) -> argparse.Namespace`
- Produces: schema constants `INPUT_SCHEMA_VERSION` and `REPORT_SCHEMA_VERSION`

- [ ] **Step 1: Write failing contract tests**

Add tests named `test_load_minimal_input_applies_defaults`, `test_rejects_invalid_wallet_or_non_utc_window`, and `test_write_report_json_is_deterministic`. Assert the exact default wallet, chain `999`, seven-day/current-day behavior from an injected `now`, lowercase normalized addresses, sorted JSON keys, and actionable validation messages.

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `python -m unittest skills.vfat-position-report.tests.test_contracts -v`

Expected: import failure because `vfat_report.contracts` does not exist.

- [ ] **Step 3: Implement the minimum contracts and entry point**

Use frozen dataclasses for `ReportInput`, `PositionInput`, `ActivityInput`, `CapitalPoint`, `TokenAmount`, `Valuation`, `NormalizedTransaction`, `DailyAggregate`, `Diagnostics`, and `Report`. Reject naive timestamps and non-EVM addresses at the boundary. Accept an explicit `--now` only for tests/reproducibility.

- [ ] **Step 4: Run the contract tests and verify GREEN**

Run: `python -m unittest skills.vfat-position-report.tests.test_contracts -v`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

Commit only the Task 1 files with message `feat: add versioned VFAT report contracts`.

## Task 2: Time-Weighted Daily Capital

**Files:**
- Create: `skills/vfat-position-report/scripts/vfat_report/capital.py`
- Create: `skills/vfat-position-report/tests/test_capital.py`
- Create: `skills/vfat-position-report/tests/fixtures/capital-history.json`

**Interfaces:**
- Consumes: `PositionInput`, `CapitalPoint` from Task 1
- Produces: `aggregate_daily_capital(positions, start, end, minimum_coverage=Decimal("0.75")) -> Mapping[date, DailyCapital]`
- Produces: `DailyCapital(average_usd, coverage_ratio, status, reasons)`

- [ ] **Step 1: Write failing capital tests**

Add `test_time_weighted_capital_carries_last_observation`, `test_time_weighted_capital_reports_gap_and_threshold`, `test_closed_position_contributes_only_while_active`, and `test_partial_first_day_is_kept_with_null_value`. Use exact Decimal assertions for a two-position synthetic day and assert that 74% coverage returns `average_usd=None`, while 75% remains usable.

- [ ] **Step 2: Run the capital tests and verify RED**

Run: `python -m unittest skills.vfat-position-report.tests.test_capital -v`

Expected: import failure because `vfat_report.capital` does not exist.

- [ ] **Step 3: Implement piecewise-constant integration**

Clip every lineage to its active interval and the requested UTC day, carry the last known value only across intervals justified by source coverage, sum simultaneous position balances, and divide the USD-seconds integral by covered seconds. Preserve a reason for every uncovered interval.

- [ ] **Step 4: Run the capital tests and verify GREEN**

Run: `python -m unittest skills.vfat-position-report.tests.test_capital -v`

Expected: all Task 2 tests pass.

- [ ] **Step 5: Commit Task 2**

Commit with message `feat: calculate time-weighted daily capital`.

## Task 3: Transaction Merging and Onchain Cost Decoding

**Files:**
- Create: `skills/vfat-position-report/scripts/vfat_report/events.py`
- Create: `skills/vfat-position-report/profiles/hyperevm-nest.json`
- Create: `skills/vfat-position-report/tests/test_events.py`
- Create: `skills/vfat-position-report/tests/fixtures/fee-compound-receipt.json`
- Create: `skills/vfat-position-report/tests/fixtures/gas-account-compound-receipt.json`
- Create: `skills/vfat-position-report/tests/fixtures/multi-source-activity.json`

**Interfaces:**
- Consumes: activity records and token/address metadata from Task 1
- Produces: `merge_position_activity(records: Iterable[ActivityInput]) -> list[MergedActivity]`
- Produces: `decode_receipt(activity: MergedActivity, receipt: Mapping, profile: ChainProfile) -> NormalizedTransaction`
- Produces: `load_chain_profile(path: Path) -> ChainProfile`

- [ ] **Step 1: Add deterministic receipt fixtures**

Store only public onchain fields required for decoding. Include one fee-paid transaction and one gas-account transaction, plus token metadata and classified addresses in the profile. Document the source transaction hashes in fixture metadata without storing private or signed data.

- [ ] **Step 2: Write failing merge and decoder tests**

Add `test_merge_activity_deduplicates_transaction_and_sources`, `test_fee_paid_compound_uses_observed_transfer_not_configured_rate`, `test_gas_account_debit_is_separate_from_keeper_network_gas`, `test_unknown_cost_event_is_unavailable_not_zero`, and `test_log_identity_prevents_double_counting`. Assert raw integer amounts, decimals, fee ratio, payer address, and explicit null reasons.

- [ ] **Step 3: Run event tests and verify RED**

Run: `python -m unittest skills.vfat-position-report.tests.test_events -v`

Expected: import failure because `vfat_report.events` does not exist.

- [ ] **Step 4: Implement log decoding and flow classification**

Decode ERC-20 `Transfer`, pool `Mint`, VFAT route metadata, and profile-declared gas-account debit events without third-party ABI packages. Treat advertised 1.8% as a warning threshold only. Calculate network gas from receipt fields and assign it to the transaction sender; count it as user cost only when a separate user debit or user payer identity proves the expense.

- [ ] **Step 5: Run event tests and verify GREEN**

Run: `python -m unittest skills.vfat-position-report.tests.test_events -v`

Expected: all Task 3 tests pass.

- [ ] **Step 6: Commit Task 3**

Commit with message `feat: decode compound flows and automation costs`.

## Task 4: Rate-Limited RPC and Three-Layer Cache

**Files:**
- Create: `skills/vfat-position-report/scripts/vfat_report/rpc.py`
- Create: `skills/vfat-position-report/scripts/vfat_report/cache.py`
- Create: `skills/vfat-position-report/tests/test_cache_rpc.py`

**Interfaces:**
- Produces: `JsonRpcClient.get_receipt(tx_hash: str) -> Mapping | None`
- Produces: `RateLimiter.acquire(now: float) -> float`
- Produces: `ReportCache.get_receipt`, `put_receipt`, `get_snapshot`, `put_snapshot`, `get_daily`, and `put_daily`
- Consumes: schema and calculation version constants from Task 1

- [ ] **Step 1: Write failing RPC/cache tests**

Add `test_rate_limiter_never_exceeds_100_requests_per_rolling_minute`, `test_rpc_retries_retryable_errors_and_uses_backup`, `test_successful_receipt_is_immutable`, `test_missing_receipt_has_short_ttl`, `test_recent_three_days_are_marked_for_refresh`, and `test_cache_invalidates_derived_layer_only`. Use fake clocks and fake transports; no network in unit tests.

- [ ] **Step 2: Run RPC/cache tests and verify RED**

Run: `python -m unittest skills.vfat-position-report.tests.test_cache_rpc -v`

Expected: import failure because `rpc` and `cache` do not exist.

- [ ] **Step 3: Implement RPC and cache**

Use injectable clock/sleep/transport interfaces. Write cache files atomically via a sibling temporary file and `Path.replace`. Namespace by chain and lowercase wallet. Corrupt JSON is quarantined with a diagnostic rather than treated as valid or deleted silently.

- [ ] **Step 4: Run RPC/cache tests and verify GREEN**

Run: `python -m unittest skills.vfat-position-report.tests.test_cache_rpc -v`

Expected: all Task 4 tests pass.

- [ ] **Step 5: Commit Task 4**

Commit with message `feat: add bounded RPC and versioned file cache`.

## Task 5: UTC Aggregation, Cost Accounting, and APR

**Files:**
- Create: `skills/vfat-position-report/scripts/vfat_report/aggregate.py`
- Create: `skills/vfat-position-report/tests/test_aggregate.py`
- Create: `skills/vfat-position-report/tests/fixtures/normalized-week.json`

**Interfaces:**
- Consumes: `NormalizedTransaction` from Task 3 and `DailyCapital` from Task 2
- Produces: `build_daily_aggregates(transactions, capital, start, end, now) -> list[DailyAggregate]`
- Produces: `build_report(report_input, transactions, capital, diagnostics) -> Report`

- [ ] **Step 1: Write failing aggregation tests**

Add `test_aggregate_counts_unique_transactions_not_sources`, `test_completed_day_apr_uses_net_lp_minus_confirmed_gas_debit`, `test_current_day_apr_is_prorated_by_elapsed_utc_fraction`, `test_zero_activity_day_is_retained`, `test_daily_aggregate_propagates_missing_usd`, and `test_rows_are_newest_first`. Assert that fee and execution loss are not subtracted twice.

- [ ] **Step 2: Run aggregation tests and verify RED**

Run: `python -m unittest skills.vfat-position-report.tests.test_aggregate -v`

Expected: import failure because `vfat_report.aggregate` does not exist.

- [ ] **Step 3: Implement daily aggregation**

Bucket timestamps strictly by UTC date. Compute `economicNetUsd = netCompoundUsd - gasAccountDebitUsd` and annualize against daily time-weighted capital; prorate only the current UTC day. Return null with accumulated reasons when capital or material USD coverage is insufficient.

- [ ] **Step 4: Run aggregation tests and verify GREEN**

Run: `python -m unittest skills.vfat-position-report.tests.test_aggregate -v`

Expected: all Task 5 tests pass.

- [ ] **Step 5: Commit Task 5**

Commit with message `feat: aggregate daily net APR and claims`.

## Task 6: Standalone HTML and End-to-End CLI

**Files:**
- Create: `skills/vfat-position-report/scripts/vfat_report/html_report.py`
- Modify: `skills/vfat-position-report/scripts/vfat_report/cli.py`
- Create: `skills/vfat-position-report/tests/test_html_cli.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: `Report` from Task 5
- Produces: `render_html(report: Report) -> str`
- Produces: CLI command accepting `--input`, `--output-dir`, `--cache-dir`, `--refresh`, optional RPC overrides, and `--now`

- [ ] **Step 1: Write failing renderer and CLI tests**

Add `test_html_is_self_contained_and_has_dual_axes`, `test_unreliable_capital_serializes_as_chart_gap`, `test_current_day_is_marked_preliminary`, `test_html_table_uses_required_column_order`, and `test_cli_writes_deterministic_json_and_html`. Assert no `http://`, `https://`, external script, or stylesheet appears in the HTML.

- [ ] **Step 2: Run HTML/CLI tests and verify RED**

Run: `python -m unittest skills.vfat-position-report.tests.test_html_cli -v`

Expected: import failure because `html_report` does not exist or CLI output is incomplete.

- [ ] **Step 3: Implement renderer and orchestration**

Render inline SVG with vanilla JavaScript toggles, tooltips, left capital axis, right APR axis, gaps for nulls, dashed current-day segments, and the required newest-first table. Embed escaped report JSON in the document and keep the output byte-stable for identical inputs.

- [ ] **Step 4: Run the complete unit suite and verify GREEN**

Run: `python -m unittest discover -s skills/vfat-position-report/tests -v`

Expected: all tests pass and no network is contacted.

- [ ] **Step 5: Commit Task 6**

Commit with message `feat: render standalone VFAT position report`.

## Task 7: Skill Instructions, References, and Operator Guide

**Files:**
- Create: `skills/vfat-position-report/SKILL.md`
- Create: `skills/vfat-position-report/references/data-contract.md`
- Create: `skills/vfat-position-report/references/calculation-rules.md`
- Create: `docs/vfat-position-report.md`

**Interfaces:**
- Consumes: the CLI and contracts from Tasks 1–6
- Produces: a discoverable Codex skill with natural-language activation and a repeatable VFAT MCP workflow

- [ ] **Step 1: Write skill evaluation scenarios before the instructions**

Document prompts that require the skill to: use the default wallet; override wallet/date/filter; collect all positions instead of one target; distinguish fee from gas-account cost; and stop with null/warning rather than invent a missing USD value.

- [ ] **Step 2: Create `SKILL.md` and references**

Keep `SKILL.md` procedural and concise. Require VFAT MCP discovery first, exact normalized-input export second, Python execution third, diagnostics review fourth, and user-facing table/HTML delivery last. Put full schemas and formulas in the reference files.

- [ ] **Step 3: Create the project guide**

Include a quick start, defaults, MCP call sequence, input assembly, RPC limits, cache policy, output interpretation, troubleshooting, and the future `mybit-folio` handoff contract.

- [ ] **Step 4: Validate skill structure and regression suite**

Run the system skill validator specified by `skill-creator`, then run `python -m unittest discover -s skills/vfat-position-report/tests -v`.

Expected: validator succeeds and all tests pass.

- [ ] **Step 5: Commit Task 7**

Commit with message `docs: add VFAT position report skill workflow`.

## Task 8: Live VFAT/HyperEVM Smoke Test and Personal Installation

**Files:**
- Create at runtime only: normalized MCP input, cache, `report.json`, and HTML under an ignored output directory
- Install after verification: `C:\Users\petri\.codex\skills\vfat-position-report\`

**Interfaces:**
- Consumes: current VFAT MCP responses and public HyperEVM receipts
- Produces: one real seven-day report for the default wallet and the installed personal skill

- [ ] **Step 1: Assemble a live normalized input through VFAT MCP**

Use the default wallet, discover every matching NEST lineage, request hourly performance history and position activity, and record source freshness/request IDs. Do not call VFAT HTTP endpoints directly.

- [ ] **Step 2: Run the CLI against live HyperEVM RPC**

Generate the seven-day report including the current UTC day. Confirm RPC rate limiting, cache reuse, all recipient positions, fee-paid and gas-account actions, and diagnostics.

- [ ] **Step 3: Perform reconciliation checks**

Confirm unique transaction counts equal the merged VFAT activity set; gross token flow equals observed claims; automation fees come from transfers; keeper gas is not charged to the user without a debit; capital/APR gaps match the 75% rule; and a second run reuses immutable receipts.

- [ ] **Step 4: Install the verified skill**

Copy only the canonical `skills/vfat-position-report/` package into `C:\Users\petri\.codex\skills\vfat-position-report\`. Re-run the skill validator against the installed path and compare hashes for all installed source/reference files.

- [ ] **Step 5: Final verification and commit**

Run the full unit suite, a deterministic fixture report, the validator, and `git diff --check`. Commit any fixture/profile corrections with message `test: verify live VFAT report workflow`.

## Self-Review Result

- Spec coverage: all sixteen design sections map to Tasks 1–8; graph-per-position and DB remain explicitly out of scope.
- Step scan: every task has a red test/evidence step, minimal implementation step, green verification, and commit boundary.
- Type consistency: Tasks 2–6 consume dataclasses introduced in Task 1; Task 7 documents the same neutral contracts.
- Review focus: each of the five high-risk inputs has a named test in its owning task.
- Proportion: the plan fixes interfaces and observable behavior without transcribing implementation bodies.

