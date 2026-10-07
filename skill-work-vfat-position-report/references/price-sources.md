# Historical USD price sources

## Default provider

Use DefiLlama Coins as the default historical USD provider. It is public, does not require an API key, and supports contract-address lookups on HyperEVM through `hyperliquid:<token-address>` and Ethereum through `ethereum:<token-address>`.

The runner calls:

`https://coins.llama.fi/batchHistorical?coins=<url-encoded-json>`

Requests are grouped into at most 50 token/timestamp points. A quote is accepted only when its timestamp is within 15 minutes of the transaction timestamp. Store accepted quotes in the snapshot cache and reuse them on later runs.

## Valuation rules

- Gross claim USD: sum each decoded reward-token amount at its transaction-time quote.
- Automation fee USD: sum the observed fee transfers at the same transaction-time quotes.
- Net compound USD: sum the decoded token0/token1 LP mint additions at their transaction-time quotes.
- Gas-account debit USD: value the native HYPE debit with WHYPE as the configured price proxy.
- On Ethereum, normalize native ETH (zero or `0xeeee…` sentinel) to WETH `0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2` for historical price lookup; price DRV at `0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be`. This changes the quote key, not the decoded native asset or amount.
- Record `defillama:batchHistorical` as valuation provenance.

Never infer gross claims from the increase in LP value. Gross rewards and net LP additions measure different stages of the compound transaction.

## Missing prices

Provider errors, missing coins, and quotes farther than 15 minutes leave dependent valuation and APR `null` with diagnostics. Exact token-native amounts remain in the report. Ethereum receipt logs without native ETH trace evidence likewise leave total claim/fee USD and dependent net claim/APR null with `native_claim_unavailable`/`native_fee_unavailable`, even when observed DRV amounts or LP USD are known. Do not silently substitute the current price, a stablecoin peg, the 1.8% fee rate, or zero.

VFAT MCP token metadata may be used to sanity-check recent prices, but its short recent history is not a replacement for the historical provider. GeckoTerminal can be investigated manually for reconciliation, but is not an automatic fallback because pool-derived prices have different liquidity and routing semantics.

Use `--no-prices` for a token-native-only run, or `--price-api-base <url>` to point the same DefiLlama-compatible contract at another base URL.
