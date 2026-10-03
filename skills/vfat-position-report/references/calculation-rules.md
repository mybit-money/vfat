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
- `automation fee`: transfers from a tracked Sickle to the configured automation fee recipient. Calculate the observed ratio from raw transfers; compare it with 1.8% using rounding tolerance.
- `net compound`: value added to the LP according to decoded pool mint amounts and historical prices.
- `execution loss`: gross claim value minus automation fee minus net compound, when all three valuations exist.
- `gas-account debit`: explicit configured debit event. It is a portfolio cost.
- `network gas`: receipt `gasUsed × effectiveGasPrice`, shown for transparency. Do not charge it to the portfolio unless the portfolio/gas account is proven to have paid it.

## Daily APR

For a complete day:

`APR % = (net compound USD - confirmed gas-account debit USD) / average capital USD × 365 × 100`

For the current day, divide additionally by the elapsed fraction of that UTC day. Do not compute APR if capital is non-positive/unreliable or a required USD valuation is missing.

All monetary sums are transaction totals across every selected position. `claimTransactionCount` is the number of unique compound/claim transactions, not the number of position activity records.
