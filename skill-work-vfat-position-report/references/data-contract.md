# Normalized data contract

The runner consumes UTF-8 JSON with `schemaVersion: "1.0"`. This boundary deliberately separates VFAT MCP collection from deterministic local calculation.

## Input

```json
{
  "schemaVersion": "1.0",
  "wallet": "0x...",
  "period": {"from": "2026-09-27T00:00:00Z", "to": "2026-10-03T12:00:00Z"},
  "filters": {"chainIds": [999], "protocols": ["nest"], "rewardTokens": []},
  "positions": [{
    "positionId": "manager:tokenId",
    "chainId": 999,
    "protocol": "nest",
    "positionType": "nft",
    "sickleAddress": "0x...",
    "tokenId": "91811",
    "nftManagerAddress": "0x...",
    "activeFrom": null,
    "activeTo": null,
    "metadata": {
      "poolAddress": "0x...",
      "underlying": [
        {"address": "0x...", "symbol": "TOKEN0", "decimals": 18},
        {"address": "0x...", "symbol": "TOKEN1", "decimals": 6}
      ]
    }
  }],
  "activities": [{
    "chainId": 999,
    "transactionHash": "0x...",
    "timestamp": "2026-10-03T10:00:00Z",
    "actionType": "compound",
    "sourcePositionIds": ["manager:tokenId"],
    "recipientPositionId": "manager:otherTokenId",
    "isAutomation": true,
    "automationPaymentMethod": "gas-account"
  }],
  "capitalPoints": [{
    "positionId": "manager:tokenId",
    "timestamp": "2026-10-03T09:00:00Z",
    "currentBalanceUsd": "2476.12",
    "totalPnlUsd": "176.54"
  }],
  "source": {"provider": "vfat-mcp", "collectedAt": "2026-10-03T12:01:00Z"}
}
```

Resolve each unique pool with VFAT MCP and populate `metadata.poolAddress` plus the first two entries of `metadata.underlying`; these fields let the decoder support newly discovered pools without code changes. Transform VFAT `blockTimestamp` to `timestamp`. Attach a stable `positionId` to every history point. Preserve the hourly `totalPnlUsd` beside `currentBalanceUsd`, including at least one point immediately before `period.from` for every already-active position; this baseline makes the first daily PnL computable. Store source and recipient relationships when known; absence is `null`/an empty array, not a guessed position.

Addresses and transaction hashes are lowercase hexadecimal. Timestamps include `Z` and are UTC. Decimal values are strings; raw token amounts remain integers. Include positions that were active for any part of the requested period, including closed or migrated lineage when VFAT returns it.

## Output

`report.json` contains:

- `inputSummary`: requested `from`/`to` plus `historyFrom`/`historyTo` for all saved capital and activity observations and `pnlFrom`/`pnlTo` for observations with VFAT `totalPnlUsd`;
- `days`: descending UTC rows with status, average capital, end-of-day position value, raw daily position-value change, cumulative/daily economic PnL, net claim, estimate flags, coverage, gross claims, net compound, automation fee, gas-account debit, realized APR, unique claim transaction count, token-native rewards, and reason codes;
- `transactions`: decoded, deduplicated chain transactions with all source/recipient position IDs, token amounts, valuation provenance, gas-account debit, network gas, and warnings;
- `diagnostics`: cache/RPC/receipt warnings and endpoints used;
- `inputSummary`: wallet, period, chains, and protocols.

An unavailable USD valuation is `null` plus a reason code. Zero means a confirmed economic zero only.

The compatible daily fields added for portfolio analysis are:

- `position_value_usd`: closing marked value of active positions;
- `daily_position_value_change_usd`: raw close-to-close value change, including capital flows;
- `net_claim_usd`: gross claim less observed automation fee and confirmed gas-account debit;
- `pnl_is_estimated`: compatible summary indicating that at least one reported PnL metric uses the verified-opening interpolation rule;
- `cumulative_pnl_is_estimated`: the closing cumulative PnL is interpolated;
- `daily_pnl_is_estimated`: either boundary used by daily economic PnL is interpolated;
- `position_value_is_estimated`: the closing position value uses first-point backfill;
- `daily_position_value_change_is_estimated`: either boundary used by raw daily value change uses first-point backfill.

## Integration stability

This JSON is the interchange contract for a future `mybit-folio` database adapter. Keep field meaning and schema version stable, retain fixture-based golden examples, and add fields compatibly before introducing a new major schema version.
