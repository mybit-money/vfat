# Calculation and reconciliation rules

## Period and deduplication

- Split days at `00:00:00 UTC`; retain zero-activity days.
- Include the current partial UTC day by default.
- Deduplicate by `(chainId, transactionHash)`. One compound transaction may appear in several position activity feeds but counts once.
- Preserve the union of source and recipient position IDs for transaction-level drill-down.

## Capital

Reconstruct each active position with last observation carried forward. Integrate capital over time and divide by elapsed seconds to obtain time-weighted daily average capital. Aggregate position capital before computing APR.

Coverage is the portion of the elapsed day for which all active positions have a known value. Coverage below 75% makes capital and APR `null`/unreliable. A partial first or current day remains labeled `partial` when coverage is sufficient.

## Claim, compound, and costs

- `gross claim`: reward-token transfers from the configured claim source to a tracked Sickle.
- `automation fee`: transfers from a tracked Sickle to the configured automation fee recipient. Calculate the observed ratio from raw transfers; compare it with 1.8% allowing one raw unit of rounding per fee transfer. A fee-paid automation without an observed fee transfer has an unknown (`null`) fee, not zero.
- `net compound`: value added to the LP according to decoded pool mint amounts and historical prices. A Mint counts only when the position manager's following `IncreaseLiquidity` names a selected position (`nftManagerAddress` + `tokenId`). A claim or harvest without an LP mint is income: it is valued as gross claim minus automation fee and counts toward APR; a compound without an attributable mint is `null` with `lp_addition_not_found`.
- `execution loss`: gross claim value minus automation fee minus net compound, when all three valuations exist.
- `gas-account debit`: explicit configured debit event. It is a portfolio cost. A gas-account automation without a decoded debit, or with several debits in one receipt that cannot be attributed, has an unknown (`null`) debit.
- `network gas`: receipt `gasUsed × effectiveGasPrice`, shown for transparency. Do not charge it to the portfolio unless the portfolio/gas account is proven to have paid it.

## Historical USD valuation

Use transaction-time quotes from DefiLlama Coins `batchHistorical`, addressed as `hyperliquid:<token-address>` on chain 999. Batch at most 50 token/timestamp points and accept only quotes within 15 minutes. Cache accepted quotes and preserve `defillama:batchHistorical` as provenance.

Value gross reward transfers, observed automation-fee transfers, and both decoded LP mint tokens independently. Value a gas-account HYPE debit through the configured WHYPE proxy. Missing, stale, or unavailable quotes produce `null` with a reason; never replace them with current prices, assumed pegs, or zero. See [price-sources.md](price-sources.md).

## Daily APR

For a complete day:

`APR % = (net compound USD - confirmed gas-account debit USD) / average capital USD × 365 × 100`

For a partial day (a first day cut by `period.from`, a last day cut by `period.to`, or the current day), divide additionally by the elapsed fraction of that UTC day, matching the span over which capital is averaged. Do not compute APR if capital is non-positive/unreliable or a required USD valuation is missing.

All monetary sums are transaction totals across every selected position. `claim_transaction_count` is the number of unique compound/claim transactions, not the number of position activity records.
