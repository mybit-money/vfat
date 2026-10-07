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
- use universal VFAT discovery; select HyperEVM/NEST or Ethereum/Uniswap V4 only when the corresponding adapter supports the position, otherwise retain capital/PnL and mark transaction metrics unavailable;
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

## 8. Ethereum CL300-ETH/DRV, fourteen UTC days

Prompt: “Покажи CL300-ETH/DRV на Ethereum за 14 дней, включая текущий день.”

Expected decisions:

- Discover positions and performance through VFAT MCP, then collect hourly history with `get_position_performance_history` for chain 1, Sickle `0xfb12aa1f51ba66ef761def09233946a4369b0de6`, and exact root `bd216513d74c8cf14cf4747e6aaa6420ff64ee9e:413470`.
- Collect all lineage activity through `get_position_activity`, including the predecessor connection; retain every in-window activity. The pinned September 24–October 7 fixture includes six compounds. Its September 23 rebalance is pre-window lineage evidence, never report-day income.
- Construct schema `1.0` with one stable root-derived `positionId`, the exact `positionRootTokenId`, and current `tokenId` `413473`. Carry the Ethereum manager, zero-hooks PoolKey, PoolManager/pool ID and ETH/DRV underlying metadata from reviewed evidence.
- Let the runner select `(1, "uniswap_v4")` automatically. Price native ETH through Ethereum WETH and DRV through its Ethereum address. Never use HyperEVM endpoints, token addresses or decoder paths.
- Preserve observed raw DRV claims/fees and selected-pool LP additions. Receipt-only evidence does not establish native ETH claim/fee amounts: expect `native_claim_unavailable` and `native_fee_unavailable`, with null total claim, fee, net claim and affected APR. A manual action label does not erase an observed fee.
- Network gas is informational; no gas-account debit means no portfolio gas charge. Reopened rebalance principal is not compound income.
- Preserve all 264 captured history points and their original gaps. The current capital engine carries the last observation forward; its complete coverage status is not proof of continuous hourly sampling. October 7 ends at settled data through 09:00 UTC and is partial.
- Base/Aerodrome remains unsupported until `(8453, "aerodrome")` is registered; never substitute the Ethereum or HyperEVM adapter.

Offline reproduction, from `skill-work-vfat-position-report`:

```text
python -m unittest tests.test_ethereum_report_e2e -v
```

This calls the public runner with real JSON input, real RPC/price clients and fixture-only transports, writes temporary `report.json` and `report.html`, and checks the reviewed golden. All network access is blocked in the test. For persistent local artifacts using the same offline replay:

```text
python -c "from pathlib import Path; from tests.test_ethereum_report_e2e import replay; replay(Path('offline-ethereum-report'), Path('offline-ethereum-cache'))"
```

Evidence lives in `tests/fixtures/ethereum-uniswap-v4`: normalized input and MCP activity provenance, six in-window receipts, historical price responses, trace-attempt errors, and the expected stable report subset. The native trace attempts returned unavailable/archive-access errors; no private key or signing operation is required.

Failure: omitting an activity because its receipt is missing, treating partial token evidence as a complete claim, inventing APR, changing the lineage ID at rebalance, backfilling fabricated hourly observations, or contacting VFAT over HTTP instead of MCP.
