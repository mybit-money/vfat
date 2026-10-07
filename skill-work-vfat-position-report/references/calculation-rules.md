# Calculation and reconciliation rules

## Period and deduplication

- Split days at `00:00:00 UTC`; retain zero-activity days.
- Include the current partial UTC day by default.
- Deduplicate by `(chainId, transactionHash)`. One compound transaction may appear in several position activity feeds but counts once.
- Preserve the union of source and recipient position IDs for transaction-level drill-down.
- Preserve a root-derived `positionId` across NFT rebalance while `tokenId` records the current NFT; exclude pre-window lineage/reopened principal from report-day compound income.

## Capital

Reconstruct each active position with last observation carried forward. Integrate capital over time and divide by elapsed seconds to obtain time-weighted daily average capital. Aggregate position capital before computing APR.

Coverage is the portion of the elapsed day for which all active positions have a known value. Coverage below 75% makes capital and APR `null`/unreliable. A partial first or current day remains labeled `partial` when coverage is sufficient.

## Portfolio value and PnL

- End-of-day position value is the aggregate `currentBalanceUsd` of positions active at the UTC close. Daily position-value change is the closing value minus the opening value. This raw change includes capital flows and is not investment performance.
- Aggregate each position's last known `totalPnlUsd` at the UTC close; use the latest available point for the current partial day. Daily economic PnL is the change in aggregate cumulative PnL from the previous UTC close. Fetch a point immediately before the report window as the first-day baseline.
- For a position with verified `activeFrom` but no VFAT history until after a required boundary, create a synthetic `totalPnlUsd = 0` anchor at `activeFrom` and linearly interpolate to the first VFAT PnL point. Estimate position value before the first point by carrying that first `currentBalanceUsd` backward to `activeFrom`.
- Before `activeFrom`, that position contributes zero to the aggregate boundary. Therefore an opening-day raw value change includes the newly added position value, while economic PnL starts from zero.
- Mark boundaries independently: `cumulative_pnl_is_estimated` for the closing PnL, `daily_pnl_is_estimated` when either daily PnL boundary is estimated, `position_value_is_estimated` for the closing value, and `daily_position_value_change_is_estimated` when either value-change boundary is estimated. Keep `pnl_is_estimated` as a compatible summary. Show `≈` and “оценка” only beside the affected metric. Do not estimate when `activeFrom` is unavailable.
- Opening-gap boundary estimates do not backfill the time-weighted average-capital integration. Capital coverage and APR continue to use measured/LOCF history and may remain partial or unreliable.
- Do not add claims or compounds to VFAT `totalPnlUsd`; those cash flows are already part of VFAT's position-performance accounting and adding them again would double-count the strategy result.
- Chart average waterlines use completed UTC days only and exclude null values.

## Claim, compound, and costs

- `gross claim`: reward-token transfers from the configured claim source to a tracked Sickle.
- `automation fee`: transfers from a tracked Sickle to the configured automation fee recipient. Calculate the observed ratio from raw transfers; compare it with 1.8% using rounding tolerance.
- On Ethereum V4, receipt logs may prove DRV claims/fees and selected-pool LP additions without proving native ETH claim/fee amounts. An opaque native-fee event does not encode a verified amount. Preserve observed raw amounts, use `native_claim_unavailable`/`native_fee_unavailable` for incomplete totals, and leave dependent USD, net claim, and APR null. Do not infer fees from 1.8%, assume a manual action is fee-free, or use LP additions as a proxy for gross claims.
- `net compound`: value added to the LP according to decoded pool mint amounts and historical prices.
- `net claim`: gross claim minus observed automation fee minus confirmed gas-account debit. It describes the reward cash flow after direct collection costs, not the amount added to LP.
- `execution loss`: gross claim value minus automation fee minus net compound, when all three valuations exist.
- `gas-account debit`: explicit configured debit event. It is a portfolio cost.
- `network gas`: receipt `gasUsed × effectiveGasPrice`, shown for transparency. Do not charge it to the portfolio unless the portfolio/gas account is proven to have paid it.

Missing receipts yield `receipt_unavailable`; a known adapter with an unsupported position fails `adapter_position_unsupported` before RPC. An unregistered `(chainId, protocolType)` yields `chain_protocol_unsupported` for transaction fields while capital/PnL can still be reported. Never decode a receipt with a different chain/protocol adapter.

## Historical USD valuation

Use transaction-time quotes from DefiLlama Coins `batchHistorical`, addressed as `hyperliquid:<token-address>` on chain 999 or `ethereum:<token-address>` on chain 1. Normalize Ethereum native ETH to WETH only for historical price lookup; retain the native ETH identity in decoded amounts. Batch at most 50 token/timestamp points and accept only quotes within 15 minutes. Cache accepted quotes and preserve `defillama:batchHistorical` as provenance.

Value gross reward transfers, observed automation-fee transfers, and both decoded LP mint tokens independently. Value a gas-account HYPE debit through the configured WHYPE proxy. Missing, stale, or unavailable quotes produce `null` with a reason; never replace them with current prices, assumed pegs, or zero. See [price-sources.md](price-sources.md).

## Daily APR

For a complete day:

`APR % = (net compound USD - confirmed gas-account debit USD) / average capital USD × 365 × 100`

For the current day, divide additionally by the elapsed fraction of that UTC day. Do not compute APR if capital is non-positive/unreliable, a required USD valuation is missing, or transaction evidence is incomplete under a fail-closed reason such as `native_claim_unavailable`, `native_fee_unavailable`, or `claim_principal_separation_unavailable`.

All monetary sums are transaction totals across every selected position. `claimTransactionCount` is the number of unique compound/claim transactions, not the number of position activity records.
The average net-claim waterline uses completed UTC days in the report period, including confirmed zero-claim days.
