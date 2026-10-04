# Historical USD price sources

## Default provider

Use DefiLlama Coins as the default historical USD provider. It is public, does not require an API key, and supports contract-address lookups on HyperEVM through the `hyperliquid:<token-address>` namespace.

The runner calls:

`https://coins.llama.fi/batchHistorical?coins=<url-encoded-json>`

Requests are grouped into at most 50 token/timestamp points. A quote is accepted only when its timestamp is within 15 minutes of the transaction timestamp. Store accepted quotes in the snapshot cache and reuse them on later runs.

## Valuation rules

- Gross claim USD: sum each decoded reward-token amount at its transaction-time quote.
- Automation fee USD: sum the observed fee transfers at the same transaction-time quotes.
- Net compound USD: sum the decoded token0/token1 LP mint additions at their transaction-time quotes.
- Gas-account debit USD: value the native HYPE debit with WHYPE as the configured price proxy.
- Record `defillama:batchHistorical` as valuation provenance.

Never infer gross claims from the increase in LP value. Gross rewards and net LP additions measure different stages of the compound transaction.

## Missing prices

Provider errors, missing coins, and quotes farther than 15 minutes leave the affected valuation and APR `null` with diagnostics. Exact token-native amounts remain in the report. Do not silently substitute the current price, a stablecoin peg, or zero.

VFAT MCP token metadata may be used to sanity-check recent prices, but its short recent history is not a replacement for the historical provider. GeckoTerminal can be investigated manually for reconciliation, but is not an automatic fallback in version 1.1 because pool-derived prices have different liquidity and routing semantics.

Use `--no-prices` for a token-native-only run, or `--price-api-base <url>` to point the same DefiLlama-compatible contract at another base URL.
