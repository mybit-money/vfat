# VFAT Multi-Chain Report Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Ethereum Uniswap V4 reporting for the `CL300-ETH/DRV` lineage while preserving byte-for-byte-significant HyperEVM/NEST report behavior and making later chain/protocol support additive.

**Architecture:** Resolve one immutable adapter from `(chain_id, protocol_type)` before any RPC call. The runner retains generic orchestration, capital/PnL aggregation, pricing, JSON, and HTML; adapters own profiles, RPC defaults, price-address normalization, position validation, and receipt decoding. Unsupported and mixed inputs fail closed without borrowing another adapter's RPC, decoder, or price namespace.

**Tech Stack:** Python 3 standard library, `unittest`, EVM JSON-RPC receipts, DefiLlama historical prices, normalized VFAT schema `1.0`, VFAT MCP for discovery/collection only.

**Spec:** `docs/superpowers/specs/2026-10-07-vfat-multichain-adapters-design-final.md`

## Global Constraints

- The canonical implementation tree is `skill-work-vfat-position-report/`; update the installed skill only after the workspace copy passes the complete suite and skill scenarios.
- Keep `schemaVersion` equal to `"1.0"` and accept existing chain-999/NEST inputs unchanged.
- Use VFAT MCP tools for VFAT discovery and normalized input collection; tests and implementation must not call VFAT HTTP endpoints.
- One invocation supports exactly one adapter; mixed adapters fail before RPC with `mixed_report_adapters_unsupported`.
- Never substitute zero, a current price, an assumed peg, or an inferred 1.8% fee for unavailable evidence.
- Preserve existing 15-minute historical-price freshness and existing capital, PnL, aggregation, JSON, and HTML rules.
- Ethereum constants are chain ID `1`, PoolManager `0x000000000004444c5dc75cb358380d2e3de08a90`, pool ID `0x20ae5557f7d6ce39a6e5370c331106a87a80ea5c1bec686361bde2d9f5e82631`, WETH `0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2`, and DRV `0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be`.
- Native ETH and `0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee` normalize to WETH for historical pricing; token-native report amounts retain their decoded token identity.
- V4 liquidity decoding must use reviewed official ABI event signatures and the PositionManager/PoolManager settlement sequence, never the Uniswap V3 `Mint` topic.

## Review Focus

- A chain-1 position without `metadata.protocolType` must be rejected as ambiguous before RPC, rather than inferred as Uniswap V4 (Task 1).
- An explicit `--adapter` that differs from any derived position key must fail before RPC with `adapter_override_mismatch` (Tasks 1 and 5).
- A receipt containing both the selected pool and another V4 pool must count only settlement attributable to the configured `poolId` (Task 4).
- A native-ETH price request and an `0xeeee…` price request must share one WETH quote without changing the decoded token amount (Task 3).
- Reading a legacy `cache/<chain>/<wallet>` entry must work for `(999, nest)`, but Ethereum must never read it (Task 3).

---

## File Structure

- `scripts/vfat_report/adapters/base.py`: `AdapterKey`, adapter protocol, resolution/decode errors, and unavailable-transaction helper.
- `scripts/vfat_report/adapters/registry.py`: adapter registration, input-key derivation, override validation, and single-adapter resolution.
- `scripts/vfat_report/adapters/hyperevm_nest.py`: existing HyperEVM profile enrichment and receipt decoder behind the adapter interface.
- `scripts/vfat_report/adapters/ethereum_uniswap_v4.py`: Ethereum constants, price normalization, V4 receipt decoder, and pool validation.
- `scripts/vfat_report/adapters/__init__.py`: stable public adapter exports only.
- `scripts/vfat_report/contracts.py`: optional lineage root and metadata parsing without a schema-version bump.
- `scripts/vfat_report/events.py`: adapter-neutral activity merge/types and only shared EVM log primitives used by both adapters.
- `scripts/vfat_report/cache.py`: adapter-aware cache namespace with a read-only HyperEVM legacy fallback.
- `scripts/vfat_report/prices.py`: caller-supplied DefiLlama namespace and price-token resolver.
- `scripts/vfat_report/runner.py`: generic orchestration through a resolved adapter and fail-closed unavailable path.
- `scripts/vfat_report/cli.py`: optional diagnostic `--adapter` argument.
- `profiles/ethereum-uniswap-v4.json`: reviewed Ethereum addresses, tokens, and ABI topic identifiers needed by the adapter.
- `tests/fixtures/ethereum-uniswap-v4/`: normalized lineage input, three raw receipts, deterministic quotes, and expected 14-day output.

### Task 1: Extend the input contract and resolve adapter keys

**Files:**
- Create: `skill-work-vfat-position-report/scripts/vfat_report/adapters/__init__.py`
- Create: `skill-work-vfat-position-report/scripts/vfat_report/adapters/base.py`
- Create: `skill-work-vfat-position-report/scripts/vfat_report/adapters/registry.py`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/contracts.py:22-34,183-296,299-369`
- Modify: `skill-work-vfat-position-report/tests/fixtures/minimal-input.json`
- Create: `skill-work-vfat-position-report/tests/test_adapter_registry.py`
- Modify: `skill-work-vfat-position-report/tests/test_contracts.py`

**Interfaces:**
- Produces: `AdapterKey(chain_id: int, protocol_type: str)` with `parse(value: str) -> AdapterKey` and `__str__() -> str` returning `<chain-id>:<protocol-type>`.
- Produces: `AdapterResolutionError(code: str)` whose `str(error)` is the stable reason code.
- Produces: `derive_adapter_key(position: PositionInput, report_protocols: tuple[str, ...]) -> AdapterKey`.
- Produces: `resolve_adapter_key(positions: tuple[PositionInput, ...], report_protocols: tuple[str, ...], override: str | None = None) -> AdapterKey`.
- Extends: `PositionInput.position_root_token_id: str | None = None`; `metadata` remains a mapping and carries `protocolType`, `poolId`, and `poolManagerAddress`.

- [ ] **Step 1: Write failing contract tests**

Add tests proving that `positionRootTokenId` is copied unchanged, current `tokenId` stays separate, and the existing minimal chain-999 fixture still parses with no new required field. Add a new chain-1 input asserting that `metadata.protocolType == "uniswap_v4"`, the exact pool ID is retained, and `position_id` uses the stable lineage root supplied by the normalized input.

- [ ] **Step 2: Run the contract tests and confirm failure**

Run: `python -m unittest tests.test_contracts -v`

Expected: FAIL because `PositionInput` has no `position_root_token_id` field and the new metadata case is not covered.

- [ ] **Step 3: Implement lineage parsing in `contracts.py`**

Parse optional `positionRootTokenId` into `PositionInput.position_root_token_id`, retain metadata verbatim after existing address validation, and include lineage/protocol metadata in history-compatibility checks so incompatible fragments cannot merge. Do not change schema version or legacy defaults.

- [ ] **Step 4: Run the contract tests**

Run: `python -m unittest tests.test_contracts tests.test_history_compatibility tests.test_history_merge -v`

Expected: PASS.

- [ ] **Step 5: Write failing registry tests**

Cover exact outcomes: legacy `(999, nest)` inference only for `report_protocols == ("nest",)`, explicit `(1, uniswap_v4)` selection, chain 1 without `protocolType` raising `adapter_protocol_type_required`, two distinct keys raising `mixed_report_adapters_unsupported`, malformed override raising `invalid_adapter_override`, and a nonmatching override raising `adapter_override_mismatch`.

- [ ] **Step 6: Run the registry tests and confirm failure**

Run: `python -m unittest tests.test_adapter_registry -v`

Expected: FAIL because the adapter base and registry modules do not exist.

- [ ] **Step 7: Implement `AdapterKey`, errors, derivation, and single-key resolution**

Keep the registry lookup separate from key derivation. Normalize protocol types to lowercase; reject empty position sets with `report_adapter_unresolved`; never infer a non-NEST protocol.

- [ ] **Step 8: Run the focused tests**

Run: `python -m unittest tests.test_adapter_registry tests.test_contracts tests.test_history_compatibility tests.test_history_merge -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add skill-work-vfat-position-report/scripts/vfat_report/contracts.py skill-work-vfat-position-report/scripts/vfat_report/adapters skill-work-vfat-position-report/tests/test_adapter_registry.py skill-work-vfat-position-report/tests/test_contracts.py skill-work-vfat-position-report/tests/fixtures/minimal-input.json
git commit -m "feat: resolve VFAT report adapter keys"
```

### Task 2: Freeze HyperEVM behavior and extract its adapter

**Files:**
- Create: `skill-work-vfat-position-report/tests/fixtures/hyperevm-golden-report.json`
- Create: `skill-work-vfat-position-report/tests/test_hyperevm_golden.py`
- Create: `skill-work-vfat-position-report/scripts/vfat_report/adapters/hyperevm_nest.py`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/adapters/base.py`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/adapters/registry.py`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/events.py:18-265`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/runner.py:93-134`
- Modify: `skill-work-vfat-position-report/tests/test_events.py`
- Modify: `skill-work-vfat-position-report/tests/test_runner.py`
- Modify: `skill-work-vfat-position-report/tests/test_runner_dynamic_profile.py`

**Interfaces:**
- Consumes: `AdapterKey`, `PositionInput`, `MergedActivity`, `DecodedTransaction` from Task 1/current event contracts.
- Produces: runtime-checkable `ReportAdapter` protocol with immutable attributes `key`, `chain_profile`, `default_rpc_endpoints`, `price_chain_slug` and methods `normalize_price_token(address: str) -> str`, `supports_position(position: PositionInput) -> bool`, `profile_for_positions(positions: tuple[PositionInput, ...]) -> ChainProfile`, `decode_receipt(activity: MergedActivity, receipt: Mapping[str, Any], positions: tuple[PositionInput, ...]) -> DecodedTransaction`.
- Produces: `HyperEvmNestAdapter` registered under `AdapterKey(999, "nest")` with the current profile, topics, fee recipient, claim sources, gas-account debit event, 1.8% comparison, and RPC defaults unchanged.

- [ ] **Step 1: Create the pre-extraction golden fixture and test**

Using only existing `fee-compound-receipt.json`, `gas-account-compound-receipt.json`, `capital-history.json`, and deterministic price quotes, record the current normalized transaction fields, daily aggregate fields, diagnostics, and stable HTML facts. Assert exact raw token amounts and fee rates already pinned by `test_events.py`; compare structured JSON values rather than the entire HTML string.

- [ ] **Step 2: Run the golden and existing HyperEVM tests before extraction**

Run: `python -m unittest tests.test_hyperevm_golden tests.test_events tests.test_runner tests.test_runner_dynamic_profile -v`

Expected: PASS; this is the baseline gate.

- [ ] **Step 3: Add the failing adapter-shape test**

Assert registry lookup for `AdapterKey(999, "nest")` returns `HyperEvmNestAdapter`, its defaults equal `("https://rpc.hyperliquid.xyz/evm", "https://rpc.hypurrscan.io")`, its price slug is `hyperliquid`, and both current profile-enrichment tests pass through `adapter.profile_for_positions(...)`.

- [ ] **Step 4: Run the adapter-shape test and confirm failure**

Run: `python -m unittest tests.test_runner tests.test_runner_dynamic_profile -v`

Expected: FAIL because `HyperEvmNestAdapter` is not registered.

- [ ] **Step 5: Extract `HyperEvmNestAdapter`**

Move, without semantic edits, HyperEVM profile enrichment and receipt decoding behind the interface. Leave activity merging and genuinely shared log primitives in `events.py`; retain compatibility imports for `decode_receipt` and `profile_for_positions` until all internal callers and existing tests are migrated.

- [ ] **Step 6: Run the HyperEVM regression gate**

Run: `python -m unittest tests.test_hyperevm_golden tests.test_events tests.test_runner tests.test_runner_dynamic_profile tests.test_profile_coverage -v`

Expected: PASS with the golden fixture unchanged.

- [ ] **Step 7: Commit**

```bash
git add skill-work-vfat-position-report/scripts/vfat_report/adapters skill-work-vfat-position-report/scripts/vfat_report/events.py skill-work-vfat-position-report/scripts/vfat_report/runner.py skill-work-vfat-position-report/tests/test_hyperevm_golden.py skill-work-vfat-position-report/tests/test_events.py skill-work-vfat-position-report/tests/test_runner.py skill-work-vfat-position-report/tests/test_runner_dynamic_profile.py skill-work-vfat-position-report/tests/fixtures/hyperevm-golden-report.json
git commit -m "refactor: isolate HyperEVM NEST reporting adapter"
```

### Task 3: Isolate cache and historical pricing by adapter

**Files:**
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/cache.py:16-139`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/prices.py:17-241`
- Modify: `skill-work-vfat-position-report/tests/test_cache_rpc.py`
- Modify: `skill-work-vfat-position-report/tests/test_prices.py`
- Modify: `skill-work-vfat-position-report/tests/test_price_failures.py`

**Interfaces:**
- Consumes: `AdapterKey` and `ReportAdapter.normalize_price_token` from Tasks 1-2.
- Changes: `ReportCache(root: Path, chain_id: int, wallet: str, *, adapter_key: AdapterKey | None = None, legacy_read_root: Path | None = None, ...)` writes adapter-aware data to `<root>/<chain>/<protocol>/<wallet>`; `(999, nest)` may read, but never write, `<root>/999/<wallet>`.
- Changes: `DefiLlamaPriceClient.get_quotes(requests: Iterable[tuple[str, datetime]], *, chain_slug: str) -> dict[tuple[str, int], PriceQuote]` replaces the integer `chain_id` lookup.
- Changes: `collect_price_requests(..., price_token_resolver: Callable[[str], str])` and `value_transaction(..., price_token_resolver: Callable[[str], str])` use the same normalized lookup key.

- [ ] **Step 1: Write failing cache-isolation tests**

Assert `(999, nest)` and `(1, uniswap_v4)` produce different write roots for the same wallet; a seeded legacy HyperEVM receipt/price snapshot is readable through the NEST cache; the Ethereum cache cannot see it; and writes after a legacy read land only in the adapter-aware path.

- [ ] **Step 2: Run cache tests and confirm failure**

Run: `python -m unittest tests.test_cache_rpc -v`

Expected: FAIL because `ReportCache` has no adapter namespace or legacy fallback.

- [ ] **Step 3: Implement adapter-aware cache paths**

Preserve existing TTL, immutable-day, refresh, and calculation-version behavior. Apply legacy fallback to reads of receipts and price snapshots only when `adapter_key == AdapterKey(999, "nest")`.

- [ ] **Step 4: Run cache tests**

Run: `python -m unittest tests.test_cache_rpc -v`

Expected: PASS.

- [ ] **Step 5: Write failing price-context tests**

Assert `chain_slug="ethereum"` emits `ethereum:<address>` coin IDs, `hyperliquid` behavior is unchanged, ETH sentinel and native alias requests deduplicate to one lowercase WETH key, DRV remains unchanged, valuation finds the normalized WETH quote while the original `TokenAmount.token_address` is retained, and a quote more than 900 seconds away remains unavailable.

- [ ] **Step 6: Run price tests and confirm failure**

Run: `python -m unittest tests.test_prices tests.test_price_failures -v`

Expected: FAIL because chain slug and token normalization are still hard-coded/by chain ID.

- [ ] **Step 7: Refactor historical-price calls to explicit adapter context**

Remove `CHAIN_SLUGS`; require the caller's slug and resolver for request collection and valuation. Cache normalized quote keys only. Preserve all existing unavailable reason strings.

- [ ] **Step 8: Run cache and price regressions**

Run: `python -m unittest tests.test_cache_rpc tests.test_prices tests.test_price_failures tests.test_price_cli -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add skill-work-vfat-position-report/scripts/vfat_report/cache.py skill-work-vfat-position-report/scripts/vfat_report/prices.py skill-work-vfat-position-report/tests/test_cache_rpc.py skill-work-vfat-position-report/tests/test_prices.py skill-work-vfat-position-report/tests/test_price_failures.py
git commit -m "feat: isolate VFAT cache and pricing by adapter"
```

### Task 4: Implement the Ethereum Uniswap V4 adapter from reviewed receipts

**Files:**
- Create: `skill-work-vfat-position-report/profiles/ethereum-uniswap-v4.json`
- Create: `skill-work-vfat-position-report/scripts/vfat_report/adapters/ethereum_uniswap_v4.py`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/adapters/registry.py`
- Create: `skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4/manual-compound-receipt.json`
- Create: `skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4/automated-compound-receipt.json`
- Create: `skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4/rebalance-413470-413473-receipt.json`
- Create: `skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4/activity.json`
- Create: `skill-work-vfat-position-report/tests/test_ethereum_uniswap_v4.py`
- Modify: `skill-work-vfat-position-report/tests/test_profile_coverage.py`

**Interfaces:**
- Consumes: `ReportAdapter` and shared log primitives from Tasks 1-2.
- Produces: `EthereumUniswapV4Adapter` registered under `AdapterKey(1, "uniswap_v4")`.
- Produces: `decode_receipt(...) -> DecodedTransaction` that validates the configured PoolManager and exact 32-byte pool ID before attributing liquidity settlement.
- Produces: `normalize_price_token(address: str) -> str` mapping native ETH aliases to WETH and lowercasing all other addresses.

- [ ] **Step 1: Capture and review the three receipt fixtures**

Fetch raw Ethereum receipts for the known manual compound, automated fee compound, and `413470 -> 413473` rebalance hashes already recorded in VFAT MCP activity. Keep the raw JSON-RPC result unchanged except stable pretty-printing. Review event topics against official Uniswap V4 PositionManager/PoolManager ABI signatures, then pin the observed claim-source and fee-recipient addresses in `ethereum-uniswap-v4.json`. Do not query VFAT over HTTP.

- [ ] **Step 2: Write failing profile and adapter tests**

Assert chain ID `1`, 18-decimal ETH/DRV metadata, the exact manager/PoolManager/pool IDs, `price_chain_slug == "ethereum"`, WETH normalization, support only for positions whose Sickle/manager/pool metadata matches the profile, and registry selection of `EthereumUniswapV4Adapter`.

- [ ] **Step 3: Run profile tests and confirm failure**

Run: `python -m unittest tests.test_ethereum_uniswap_v4 tests.test_profile_coverage -v`

Expected: FAIL because the profile and adapter do not exist.

- [ ] **Step 4: Implement immutable Ethereum profile loading and position validation**

Require `metadata.protocolType == "uniswap_v4"`, `metadata.poolManagerAddress` equal to the configured PoolManager, `metadata.poolId` equal to the configured pool, and the expected two underlying assets. A mismatch returns `False`; the runner will convert that to a stable resolution failure before RPC.

- [ ] **Step 5: Run the profile subset**

Run: `python -m unittest tests.test_ethereum_uniswap_v4.EthereumUniswapV4ProfileTests tests.test_profile_coverage -v`

Expected: PASS.

- [ ] **Step 6: Write failing receipt-decoding tests**

For each fixture assert transaction hash/timestamp/source lineage, exact raw gross-claim transfers, exact raw automation-fee transfers, and exact positive ETH/WETH and DRV LP additions observed in the reviewed receipt. Assert manual compound has confirmed zero fee only because no matching fee transfer exists; network gas is computed from `gasUsed * effectiveGasPrice` and remains informational; rebalance retains stable position ID/root and is counted once. Add a mutated fixture with an unrelated pool event and assert it contributes nothing; add a wrong configured pool ID and assert `pool_identity_mismatch`. Assert the V3 `Mint` topic alone can never create V4 LP additions.

- [ ] **Step 7: Run decoder tests and confirm failure**

Run: `python -m unittest tests.test_ethereum_uniswap_v4 -v`

Expected: FAIL because V4 receipt decoding is not implemented.

- [ ] **Step 8: Implement V4 receipt decoding**

Deduplicate logs by `(transactionHash, logIndex)`. Attribute gross and fee transfers only between configured endpoints. Decode liquidity change and settlement using the reviewed ABI topics; bind settlement to the selected pool ID before constructing positive LP additions. Preserve unknown token raw amounts where possible, warn when they block valuation, and never call the V3 decoder.

- [ ] **Step 9: Run Ethereum and HyperEVM decoder tests together**

Run: `python -m unittest tests.test_ethereum_uniswap_v4 tests.test_events tests.test_hyperevm_golden -v`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add skill-work-vfat-position-report/profiles/ethereum-uniswap-v4.json skill-work-vfat-position-report/scripts/vfat_report/adapters skill-work-vfat-position-report/tests/test_ethereum_uniswap_v4.py skill-work-vfat-position-report/tests/test_profile_coverage.py skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4
git commit -m "feat: decode Ethereum Uniswap V4 VFAT positions"
```

### Task 5: Route the runner and CLI through one fail-closed adapter

**Files:**
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/cli.py:11-40`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/runner.py:28-134`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/adapters/base.py`
- Modify: `skill-work-vfat-position-report/scripts/vfat_report/adapters/registry.py`
- Create: `skill-work-vfat-position-report/tests/test_runner_adapters.py`
- Modify: `skill-work-vfat-position-report/tests/test_runner.py`
- Modify: `skill-work-vfat-position-report/tests/test_price_cli.py`

**Interfaces:**
- Consumes: `resolve_adapter_key`, registered adapters, adapter-aware cache, and explicit pricing context from Tasks 1-4.
- Produces: `get_report_adapter(key: AdapterKey) -> ReportAdapter | None`.
- Produces: `unavailable_transaction(activity: MergedActivity, reason: str) -> DecodedTransaction` with token/USD values unavailable, not zero.
- Changes: CLI namespace gains `adapter: str | None` from `--adapter <chain-id>:<protocol-type>`.

- [ ] **Step 1: Write failing CLI and orchestration tests**

Use fake RPC/cache/price collaborators to assert: automatic NEST and Ethereum selection; explicit matching override succeeds; mismatch fails with `adapter_override_mismatch`; mixed keys fail with `mixed_report_adapters_unsupported` before fake RPC is called; adapter defaults are used only when `--rpc` is absent; user `--rpc` values retain precedence.

- [ ] **Step 2: Run the selection tests and confirm failure**

Run: `python -m unittest tests.test_runner_adapters tests.test_runner tests.test_price_cli -v`

Expected: FAIL because runner and CLI do not accept adapter context.

- [ ] **Step 3: Implement adapter-driven orchestration**

Resolve and validate one key immediately after input loading. If an adapter exists, validate every position with `supports_position` before constructing RPC. Pass adapter key to cache, adapter RPC defaults to the RPC client, adapter decoder to receipt processing, and adapter slug/resolver to pricing. Preserve all existing flags and output locations.

- [ ] **Step 4: Run supported-adapter tests**

Run: `python -m unittest tests.test_runner_adapters tests.test_runner tests.test_price_cli -v`

Expected: PASS for supported and mixed/override cases.

- [ ] **Step 5: Add failing unsupported/missing-receipt tests**

Assert an unknown but well-formed key never constructs RPC, still produces capital/PnL rows, and marks claim/compound/automation-cost/realized-APR values `None` with `chain_protocol_unsupported`. Assert a missing receipt retains one unavailable transaction and adds `receipt_unavailable:<hash>` without converting any transaction metric to zero.

- [ ] **Step 6: Run the fail-closed tests and confirm failure**

Run: `python -m unittest tests.test_runner_adapters -v`

Expected: FAIL until the unavailable path is implemented.

- [ ] **Step 7: Implement unavailable transaction/report paths**

Build placeholder decoded transactions from activity identity only, with all evidence-derived valuations unavailable. Ensure aggregation propagates the supplied reason to daily diagnostics and realized APR while leaving independently computed capital/PnL intact.

- [ ] **Step 8: Run runner and aggregation regressions**

Run: `python -m unittest tests.test_runner_adapters tests.test_aggregate tests.test_aggregate_non_claim tests.test_aggregate_non_claim_fee tests.test_portfolio_metrics -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add skill-work-vfat-position-report/scripts/vfat_report/cli.py skill-work-vfat-position-report/scripts/vfat_report/runner.py skill-work-vfat-position-report/scripts/vfat_report/adapters skill-work-vfat-position-report/tests/test_runner_adapters.py skill-work-vfat-position-report/tests/test_runner.py skill-work-vfat-position-report/tests/test_price_cli.py
git commit -m "feat: run VFAT reports through protocol adapters"
```

### Task 6: Prove the 14-day CL300-ETH/DRV report end to end

**Files:**
- Create: `skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4/input-14d.json`
- Create: `skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4/prices-14d.json`
- Create: `skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4/expected-report-14d.json`
- Create: `skill-work-vfat-position-report/tests/test_ethereum_report_e2e.py`
- Modify: `skill-work-vfat-position-report/tests/skill-scenarios.md`

**Interfaces:**
- Consumes: the public CLI/runner behavior completed in Task 5.
- Produces: a deterministic offline fixture report for lineage root `bd216513d74c8cf14cf4747e6aaa6420ff64ee9e:413470` and current token `413473`.

- [ ] **Step 1: Build the normalized 14-day fixture from VFAT MCP evidence**

Store the 14 UTC-day capital history and all lineage activities in schema `1.0`. Use one stable `positionId` derived from the root, `positionRootTokenId` equal to the exact root, current `tokenId == "413473"`, and exact Ethereum/V4 metadata from the spec. Reference only stored receipts from Task 4; do not add a live VFAT dependency.

- [ ] **Step 2: Add deterministic historical quotes**

Store quotes for every normalized WETH/DRV timestamp used by decoded amounts, with quote timestamps no farther than 900 seconds. Include a fake price transport that reads this fixture and fails on any unexpected coin ID or timestamp.

- [ ] **Step 3: Write the failing end-to-end test**

Run the report into a temporary output/cache directory with fake RPC and price transports. Assert exactly 14 UTC rows; stable root/current token separation; non-null claim, compound, fee, PnL, net claim, and realized APR where evidence exists; network gas is informational; report JSON and HTML are created; diagnostics contain no unavailable, pool-mismatch, stale-price, or cross-adapter warnings. Compare the stable report subset against `expected-report-14d.json`.

- [ ] **Step 4: Run the end-to-end test and confirm failure**

Run: `python -m unittest tests.test_ethereum_report_e2e -v`

Expected: FAIL on the first incomplete integration or missing fixture expectation.

- [ ] **Step 5: Make only integration-level corrections needed by the fixture**

Do not relax decoder assertions or add heuristic fallbacks. Any corrected ABI interpretation must first update the focused Task 4 fixture assertion, then the adapter, then this golden output.

- [ ] **Step 6: Run Ethereum end-to-end and focused regressions**

Run: `python -m unittest tests.test_ethereum_report_e2e tests.test_ethereum_uniswap_v4 tests.test_hyperevm_golden -v`

Expected: PASS.

- [ ] **Step 7: Document the skill scenario**

Add `CL300-ETH/DRV` collection, stable-lineage input construction, adapter auto-selection, and offline reproduction to `skill-scenarios.md`. State explicitly that Base/Aerodrome remains unsupported until `(8453, "aerodrome")` is registered.

- [ ] **Step 8: Commit**

```bash
git add skill-work-vfat-position-report/tests/fixtures/ethereum-uniswap-v4 skill-work-vfat-position-report/tests/test_ethereum_report_e2e.py skill-work-vfat-position-report/tests/skill-scenarios.md
git commit -m "test: prove 14-day Ethereum VFAT report"
```

### Task 7: Update skill guidance, verify, and publish the workspace copy

**Files:**
- Modify: `skill-work-vfat-position-report/SKILL.md`
- Modify: `skill-work-vfat-position-report/references/data-contract.md`
- Modify: `skill-work-vfat-position-report/references/calculation-rules.md`
- Modify: `skill-work-vfat-position-report/references/price-sources.md`
- Modify: `skill-work-vfat-position-report/tests/skill-scenarios.md`
- Sync after verification: `C:/Users/petri/.codex/skills/vfat-position-report/`

**Interfaces:**
- Consumes: all implemented CLI, input, adapter, and failure behavior from Tasks 1-6.
- Produces: user-facing instructions for normalized multi-chain input and a tested installed skill identical to the canonical workspace copy.

- [ ] **Step 1: Update skill instructions and references**

Document adapter selection, required non-NEST `protocolType`, lineage-root/current-token semantics, Ethereum V4 metadata, ETH-to-WETH pricing normalization, fail-closed reason codes, and the unchanged command line. Keep VFAT discovery/collection MCP-only and keep signing/transaction submission out of scope.

- [ ] **Step 2: Run documentation/scenario validation required by `superpowers:writing-skills`**

Follow that skill's validation workflow against the canonical workspace copy. Add or tighten scenarios if an instruction can be misread as permitting direct VFAT HTTP access, mixed adapters, inferred fees, or current-price fallback.

- [ ] **Step 3: Run the complete regression suite**

Run from `skill-work-vfat-position-report`:

```text
python -m unittest discover -s tests -v
```

Expected: all tests PASS, including unchanged HyperEVM goldens and the 14-day Ethereum end-to-end test.

- [ ] **Step 4: Run a clean offline CLI smoke test**

Use the checked-in 14-day input, stored receipts, deterministic quote transport, and a new temporary cache/output directory. Expected: exit code `0`, 14 rows, JSON and HTML present, and no unavailable diagnostics.

- [ ] **Step 5: Review the diff for scope and adapter isolation**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors; no unrelated user files staged; no Base/Aerodrome implementation; no direct VFAT HTTP client; no Ethereum branches inside `hyperevm_nest.py` and no HyperEVM branches inside `ethereum_uniswap_v4.py`.

- [ ] **Step 6: Commit the documentation**

```bash
git add skill-work-vfat-position-report/SKILL.md skill-work-vfat-position-report/references skill-work-vfat-position-report/tests/skill-scenarios.md
git commit -m "docs: document multichain VFAT report adapters"
```

- [ ] **Step 7: Sync the verified canonical tree to the installed skill**

Request filesystem approval for `C:/Users/petri/.codex/skills/vfat-position-report/`, copy only the verified skill files (exclude `__pycache__` and generated reports), and compare file hashes so the installed copy matches `skill-work-vfat-position-report/`.

- [ ] **Step 8: Re-run the installed skill's complete suite**

Run from `C:/Users/petri/.codex/skills/vfat-position-report`:

```text
python -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit any final canonical-only correction, otherwise record completion**

If installed verification exposes a real defect, fix it first in the canonical workspace with a failing test, repeat Steps 3-8, and commit the correction. Never patch only the installed copy.
