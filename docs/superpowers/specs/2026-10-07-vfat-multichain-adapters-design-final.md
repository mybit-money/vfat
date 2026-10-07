# VFAT Multi-Chain Report Adapters Design

## Purpose

Extend `vfat-position-report` to support the wallet's Ethereum Uniswap V4 `CL300-ETH/DRV` lineage while preserving HyperEVM/NEST behavior. A future Base/Aerodrome implementation must arrive as a new adapter rather than edits to existing protocol modules.

The canonical implementation tree is `skill-work-vfat-position-report/`. The installed skill is updated only after the workspace copy passes the complete regression suite and skill scenarios.

## Confirmed First Position

- Ethereum mainnet, `chainId = 1`
- Uniswap V4 `CL300-ETH/DRV`
- Current token ID `413473`; lineage root `413470`
- Position manager `0xbd216513d74c8cf14cf4747e6aaa6420ff64ee9e`
- PoolManager `0x000000000004444c5dc75cb358380d2e3de08a90`
- Pool ID `0x20ae5557f7d6ce39a6e5370c331106a87a80ea5c1bec686361bde2d9f5e82631`
- Underlying assets: native ETH and DRV

VFAT MCP already provides complete hourly history and lineage-aware activity. The missing capability is chain- and protocol-specific receipt decoding and valuation in the local runner.

## Goals

1. Generate the existing daily capital, PnL, claim, compound, cost, and APR report for one Ethereum V4 lineage.
2. Select a report adapter from normalized position metadata instead of loading HyperEVM directly.
3. Keep normalized schema version `1.0` and accept existing HyperEVM inputs unchanged.
4. Isolate profiles, decoders, price normalization, and RPC defaults by adapter.
5. Make Base/Aerodrome additive: a new module, fixtures, tests, and registry entry, without edits to existing adapter implementations.
6. Fail closed: unsupported or ambiguous adapters return explicit unavailable reasons and never substitute zero.

## Non-Goals

- Base/Aerodrome decoding in this release.
- Mixed-chain or mixed-adapter reports in one invocation.
- Direct VFAT HTTP access or changes to VFAT MCP collection.
- Transaction preparation, signing, or submission.
- Replacing existing capital, PnL, aggregation, HTML, cache, or price-freshness rules.

## Architecture

### Adapter key and registry

Each report resolves exactly one `AdapterKey(chain_id: int, protocol_type: str)`:

- `(999, "nest") -> HyperEvmNestAdapter`
- `(1, "uniswap_v4") -> EthereumUniswapV4Adapter`

The registry performs lookup only. Adapters do not import or modify each other. A future `(8453, "aerodrome")` registration adds a new module without touching HyperEVM or Ethereum implementations.

### Adapter interface

Each adapter exposes an immutable `ReportAdapter` with:

- `key: AdapterKey`
- `chain_profile: ChainProfile`
- `default_rpc_endpoints: tuple[str, ...]`
- `price_chain_slug: str`
- `normalize_price_token(token_address: str) -> str`
- `supports_position(position: PositionInput) -> bool`
- `decode_receipt(activity, receipt, positions) -> DecodedTransaction`

The runner continues to own cache access, RPC orchestration, price batching, capital aggregation, portfolio aggregation, JSON, and HTML. It delegates only chain/protocol decisions.

### Module layout

New modules under `scripts/vfat_report/adapters/`:

- `base.py`: adapter key, protocol, immutable types, and adapter errors.
- `registry.py`: registration and single-adapter resolution.
- `hyperevm_nest.py`: current profile and decoding behavior.
- `ethereum_uniswap_v4.py`: Ethereum profile, price normalization, and V4 decoder.

Generic helpers such as ERC-20 transfer parsing and log deduplication move to a shared module only when both adapters use them. Protocol-specific topic interpretation remains inside its adapter.

## Input Contract

`schemaVersion` remains `"1.0"`. Positions gain an optional top-level lineage field and optional metadata:

```json
{
  "positionRootTokenId": "bd216513d74c8cf14cf4747e6aaa6420ff64ee9e:413470",
  "metadata": {
    "protocolType": "uniswap_v4",
    "poolId": "0x20ae5557f7d6ce39a6e5370c331106a87a80ea5c1bec686361bde2d9f5e82631",
    "poolManagerAddress": "0x000000000004444c5dc75cb358380d2e3de08a90"
  }
}
```

`positionRootTokenId` is copied exactly from VFAT performance discovery. For new NFT inputs, `positionId` is derived from this stable root; `tokenId` stores the current NFT ID. Legacy inputs without the root preserve their existing meaning.

Existing metadata fields `poolAddress` and `underlying` remain required for decoding. For V4, `poolAddress` is the PoolManager. The first two `underlying` entries retain address, symbol, and decimals.

Legacy chain-999 inputs may omit `protocolType`; the registry infers `nest` only when `filters.protocols == ["nest"]`. Every other input must declare `protocolType`. Ambiguity is rejected before RPC access.

Collection selects the full lineage by `positionRootTokenId`. All lineage activities reference one stable `positionId`, so rebalance `413470 -> 413473` does not create a second report position or split accounting.

## Runner Flow

1. Load and validate normalized input.
2. Derive an adapter key for each position.
3. Require one shared key or stop with `mixed_report_adapters_unsupported` before RPC access.
4. Resolve the adapter. If missing, retain capital/PnL but mark transaction-derived metrics unavailable with `chain_protocol_unsupported`.
5. Namespace cache entries by chain ID, adapter key, and wallet; keep a read fallback for the legacy HyperEVM chain/wallet path.
6. Fetch receipts through CLI endpoints or adapter defaults.
7. Decode through the adapter.
8. Normalize price addresses and request historical quotes using the adapter slug.
9. Run the existing capital, aggregation, JSON, and HTML stages unchanged.

## HyperEVM/NEST Compatibility

The current profile, topics, claim sources, automation fee recipient, gas-account debit event, expected 1.8% comparison, and RPC defaults remain unchanged.

Before extraction, fixture reports become golden baselines. After wrapping the existing logic in `HyperEvmNestAdapter`, normalized transactions, daily rows, diagnostics, and key HTML values must match. Existing cache entries remain readable through the legacy fallback.

## Ethereum/Uniswap V4 Behavior

### Network and valuation

- Chain ID `1`; native gas token ETH, 18 decimals.
- Native ETH and `0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee` normalize to WETH `0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2` for historical pricing.
- DRV is `0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be`, 18 decimals.
- Historical requests use DefiLlama namespace `ethereum` and the existing 15-minute freshness limit.
- Network gas remains informational unless a separately decoded gas-account debit proves portfolio payment.

### Receipt decoding

The adapter decodes only the selected Sickle lineage and pool ID:

- Gross claim: reward-token transfers from the configured claim source to the tracked Sickle.
- Automation fee: reward-token transfers from the tracked Sickle to the configured fee recipient.
- LP additions: positive ETH/WETH and DRV committed to the selected V4 pool, derived from the PositionManager/PoolManager liquidity-change and settlement sequence and validated against `poolId`.
- The Uniswap V3 `Mint` topic is never used for V4.
- A manual compound yields confirmed zero automation fee only when no matching fee transfer exists.
- Rebalance changes the current token ID without splitting lineage or double-counting its receipt.
- Unrelated pool events are ignored; unknown transfers produce warnings when they prevent complete valuation.

Reviewed receipt fixtures cover a manual compound, automated fee compound, and the `413470 -> 413473` rebalance. Event layouts are pinned by fixture assertions and official ABI signatures, not heuristic data-word offsets.

## Failure Behavior

- Missing adapter: capital/PnL stay available; claim, compound, automation cost, and realized APR are `null` with `chain_protocol_unsupported`.
- Mixed adapters: fail before RPC with `mixed_report_adapters_unsupported`.
- Missing receipt: retain the activity as unavailable and add `receipt_unavailable:<hash>`.
- Missing/stale price: preserve token-native amounts; USD and dependent APR are `null` with existing reasons.
- Pool mismatch: stop decoding that transaction with `pool_identity_mismatch`.
- Unknown token: preserve raw amount where possible and leave USD unavailable.
- Never use current-price fallback, assumed peg, inferred 1.8% fee, or zero substitution.

## CLI Compatibility

The existing command remains valid:

```text
python scripts/vfat_position_report.py --input <input.json> --output-dir <output>
```

Adapter selection is automatic. Optional `--adapter <chain-id>:<protocol-type>` exists only for diagnostics/tests and must match all positions. Existing `--rpc`, `--history-root`, `--cache-dir`, `--refresh`, `--price-api-base`, `--no-prices`, and `--now` behavior remains unchanged.

## Testing

1. Golden tests pin current HyperEVM/NEST transactions, daily rows, diagnostics, and key HTML values before and after extraction.
2. Registry tests cover legacy inference, Ethereum selection, unknown adapter, override mismatch, and mixed-adapter rejection before RPC.
3. Ethereum fixture tests cover manual compound, automated fee, selected-pool LP additions, unrelated-pool exclusion, ETH/WETH normalization, network gas, missing prices, and lineage rebalance.
4. Cache tests prove adapter/chain isolation and legacy HyperEVM cache readability.
5. An end-to-end test builds a 14-day single-lineage Ethereum report from normalized VFAT data, stored receipts, and deterministic historical quotes, asserting non-null claim, compound, fee, PnL, and APR.
6. Skill scenarios document `CL300-ETH/DRV` collection and state that Base/Aerodrome remains unsupported until its adapter exists.

Tests never access VFAT HTTP. VFAT discovery remains MCP-only; test inputs use normalized fixtures.

## Acceptance Criteria

- A 14-day report for lineage root `413470` and current token `413473` has 14 UTC rows and clean diagnostics from complete fixtures.
- Claim, fee, LP additions, network gas, historical USD, net claim, and realized APR follow existing calculation rules.
- HyperEVM/NEST golden outputs and the existing test suite remain unchanged.
- Existing inputs without new metadata still work.
- Unsupported/mixed adapters fail closed and never use another chain's RPC or decoder.
- A later Base/Aerodrome adapter requires a new module, fixtures, tests, and registry entry, with no edits to existing adapter implementations.

