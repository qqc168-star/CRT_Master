# CRT Public Source Authority Lock V0.1

## Status

- `PUBLIC_RESEARCH_ROUTE_LOCKED_DATA_NOT_READY`
- Base: `main@a267ea84e797d41a5e973523d7d013fdf00ba773`
- Candidate registry: `62497bab3e7d551f45e6b3bc23b367575927d5be6be9f25a0956566e1d64c2ee`
- Public source authority: `b090665891e84fc8ddbccd0e07d81e3b6abc9013e76bc43f4baab5c2406261fb`
- Formal model: `NOT_APPROVED`
- Production: `NOT_APPROVED`
- External action authority: `NONE`

This lock selects the public research-source route for the five unresolved data decisions. It does not acquire history, start a walk-forward, approve the formal model, or create capital authority.

## Decision matrix

| Decision | Locked research route | What counts | What does not count | Current data state |
| --- | --- | --- | --- | --- |
| Stablecoin universe | Fixed USDT + USDC core panel from DefiLlama `stablecoin/1` and `stablecoin/2` | Both assets on the exact UTC date; `totalCirculating.peggedUSD`; hash-bound first-seen snapshot | Dynamic top-N universe, current-rank backfill, price-adjusted depeg deletion, partial panel | `NOT_PRESENT` |
| US spot BTC ETP | Official issuer daily shares, NAV, and net-assets snapshots with SEC identity anchors | Every effective-dated fund, publication time, split ledger, raw snapshot hash | SEC N-PORT alone, current issuer page assigned backward, Farside as calculation authority | `NOT_PRESENT` |
| Binance contract multiplier | Eliminated; use `sumOpenInterestValue` directly | Official notional field, checksum/local hash, gap and duplicate ledger | Guessed multiplier or `openInterest * markPrice` | `NOT_PRESENT` |
| BTC spot composite | Coinbase BTC-USD + Kraken XBT/USD + Bitstamp BTC/USD | All three complete UTC daily bars; coordinate-wise median OHLC | Single venue, two-of-three fallback, partial bar, silent venue replacement | `NOT_PRESENT` |
| BTC spot aggressor | Binance BTCUSDT spot `aggTrades` archive | `isBuyerMaker` side mapping, `price*quantity`, checksum and boundary coverage | Kline taker volume substituted without archive proof, absent file treated as zero | `NOT_PRESENT` |

## Point-in-time law

Public access is necessary but not sufficient. Every artifact must retain its exact request identity, response bytes, retrieval time, first-seen time, SHA-256, license classification, and source-document identity.

A currently retrieved historical response is not magically old. It receives the current retrieval/first-seen time unless an immutable provider archive, event-time trade record, filing timestamp, or contemporaneous hash proves earlier availability. Later provider corrections remain separate artifacts and may not leak into earlier evaluations.

No source substitution or weight renormalization is permitted. A missing member, venue, field, checksum, coverage proof, or publication timestamp blocks the dependent feature.

## Why the ETP route stays strict

SEC Form N-PORT is public and valuable, but its monthly observations and quarterly publication do not reproduce a daily 20-day creation/redemption signal. Farside publishes a useful full daily table, yet it is automatically revised, disclaims errors, and does not supply the candidate calculator's daily starting-AUM contract. It is therefore a cross-check, not the calculation authority.

The public calculation authority is the effective-dated set of official issuer snapshots. The following product URLs and membership dates are hash-locked; they identify the intended issuer sources but do not prove historical replayability.

| Ticker | Membership from | Official product source |
| --- | --- | --- |
| IBIT | 2024-01-11 | iShares / BlackRock |
| FBTC | 2024-01-11 | Fidelity Investments |
| BITB | 2024-01-11 | Bitwise Asset Management |
| ARKB | 2024-01-11 | ARK / 21Shares |
| BTCO | 2024-01-11 | Invesco / Galaxy |
| EZBC | 2024-01-11 | Franklin Templeton |
| BRRR | 2024-01-11 | CoinShares |
| HODL | 2024-01-11 | VanEck |
| BTCW | 2024-01-11 | WisdomTree |
| GBTC | 2024-01-11 | Grayscale |
| BTC | 2024-07-31 | Grayscale |
| MSBT | 2026-04-08 | Morgan Stanley Investment Management |

Before acquisition begins, each adapter must still bind the exact SEC CIK/accession identity, issuer fields, publication-time rule, split history, launch baseline, and closure/conversion handling. Those bindings and historical replay proof remain explicitly blocked; a current product page cannot satisfy them.

## Why the multiplier disappears

Binance publishes `sumOpenInterestValue`, the total open-interest notional value. Consuming that field directly removes an unnecessary scalar assumption and a cross-source price alignment. The public archive still needs a cadence, duplicate, gap, checksum, and revision audit; simpler does not mean gullible.

## Composite method

For every complete UTC day, require Coinbase BTC-USD, Kraken XBT/USD, and Bitstamp BTC/USD. Compute the median of the three opens, highs, lows, and closes independently. Store summed base volume as quality metadata only. Record venue dispersion, but do not silently drop an outlier or substitute another exchange.

The same composite close is the only permitted forward-return target. This prevents the feature from being evaluated against a friendlier benchmark after the fact.

## Aggressor convention

For Binance spot `aggTrades`:

- `isBuyerMaker = false` means the buyer was the aggressor.
- `isBuyerMaker = true` means the seller was the aggressor.
- Quote volume is `price * quantity`.

The timestamp unit transition documented by Binance must be normalized before UTC bucketing. Unknown side, checksum failure, archive gaps, duplicate IDs, or an absent daily file block the observation.

## Remaining boundary

This lock removes source-choice ambiguity, not dataset absence. Walk-forward readiness remains `BLOCKED` until all nine required source histories and a hash-bound dataset manifest pass their gates. Synthetic fixtures never count as history.

## Acquisition proof result（資料擷取證明結果）

`2026-08-11` 的 representative probe（代表性探測）檢查三種最危險的產品形態：IBIT 的 new launch（新發行）、GBTC 的 converted trust（轉換信託），以及 BTC 的 late launch with initial distribution and reverse split（含初始分配與反向拆分的晚期發行）。SEC filings（美國證券交易委員會申報）可鎖定 CIK（中央索引鍵）、上市／轉換事件與拆分事件；官方產品頁可顯示 current daily facts（當前每日資料）。但所檢查的官方介面未能證明 date-addressable immutable daily history（可按日期定址且不可變的每日歷史），因此 historical backfill（歷史回補）維持 `BLOCKED_NOT_PROVEN`。

`candidate_acquisition.py` 只實作 local content-addressed archive（本機內容定址封存）、immutable first-seen identity record（不可變首次見證身分紀錄）與 byte-verified manifest（位元組驗證資料清冊）。它沒有 network fetch（網路擷取）或 issuer adapter（發行人轉接器），也沒有取得任何 raw dataset（原始資料集）。`CURRENT_FIRST_SEEN_CAPTURE` 只能從實際首次蒐集時間向前累積；`SYNTHETIC_FIXTURE` 永遠不得滿足 source presence（來源存在）、history（歷史）或 readiness（就緒）關卡。
