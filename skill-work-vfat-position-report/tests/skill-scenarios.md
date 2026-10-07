# Skill evaluation scenarios

These scenarios are the behavioral acceptance checks for `vfat-position-report`.

## 1. Defaults under time pressure

Prompt: “Быстро покажи отчёт по NEST за неделю.”

Expected decisions:

- use wallet `0x330d2a845d2df4e329034d72719c7c53f9c1f87a`;
- use seven UTC calendar days including today;
- discover every matching position through VFAT MCP before requesting activity;
- do not ask for a target compound position.

Failure: querying only NFT 91811 or silently excluding the current UTC day.

## 2. Explicit overrides

Prompt: “Для кошелька 0x1111111111111111111111111111111111111111 построй отчёт с 2026-09-01 по 2026-09-10 только по указанному reward-токену.”

Expected decisions:

- preserve the supplied wallet, UTC dates, and token filter;
- use universal VFAT discovery, but reject unsupported onchain decoding with a clear warning if the selected chain is not HyperEVM/NEST;
- never fall back to the default wallet after an explicit override.

Failure: mixing positions or cached data from the default wallet.

## 3. Multiple and changing recipients

Prompt: “Все награды могли компаундиться в разные позиции. Дай общий итог.”

Expected decisions:

- query activity for all selected source lineages;
- deduplicate by chain and transaction hash;
- determine recipients per transaction and aggregate independently of recipient;
- keep recipient detail in `report.json` for drill-down.

Failure: requiring one target token ID or double-counting a batch transaction.

## 4. Fee versus gas account

Prompt: “Сколько ушло VFAT и сколько на gas?”

Expected decisions:

- derive VFAT fee from observed reward-token transfers;
- calculate network gas from receipt fields and report its payer;
- count gas-account cost only from a recognized debit event;
- do not charge keeper gas to the user without evidence.

Failure: multiplying every claim by 1.8% or treating keeper network gas as the user’s expense.

## 5. Missing historical USD

Prompt: “Дай APR даже если в одном swap нет USD metadata — оцени примерно.”

Expected decisions:

- retain exact token amounts;
- return null for affected USD/APR fields with a reason;
- explain the missing coverage instead of inferring claim value from LP price movement.

Failure: inventing a price, returning zero, or presenting an estimate as measured APR.

## 6. Free historical prices

Prompt: “Добавь USD и APR без платного API.”

Expected decisions:

- use DefiLlama Coins `batchHistorical` without an API key;
- map HyperEVM chain 999 to `hyperliquid:<token-address>`;
- batch no more than 50 points and cache successful quotes;
- reject quotes farther than 15 minutes and expose missing valuations as null with diagnostics;
- value LP additions token by token and HYPE gas-account debit through the configured WHYPE proxy.

Failure: using current prices for old transactions, assuming a stablecoin peg, or hiding a provider failure behind zero.

## 7. New position before first history point

Prompt: “Позиция открылась вечером, первая точка VFAT появилась утром. Не оставляй разрывы, но отметь оценки; отдельно покажи изменение стоимости, экономический PnL и чистый claim.”

Expected decisions:

- require verified `activeFrom`;
- interpolate PnL from a synthetic zero at opening to the first VFAT PnL point;
- backfill position value from the first VFAT balance only through the opening-to-first-point interval;
- mark affected PnL/value fields as estimated in JSON and HTML;
- calculate raw position-value change separately from economic PnL;
- calculate net claim as gross claim less observed automation fee and confirmed gas-account debit;
- never add claims or compounds again to VFAT `totalPnlUsd`.

Failure: leaving avoidable gaps, silently substituting zero, treating deposits as profit, or double-counting compounded rewards.
