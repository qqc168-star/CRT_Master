# CRT live runtime integration — consolidated acceptance

Status: draft engineering scope, not production approval. Existing main contracts prevail. No capital authority or source promotion.

| Work package | Implementation / dependency | Acceptance |
|---|---|---|
| A Public market | Registered spot, completed UTC daily structure, CVD20, RVOL20, taker share; Coinbase USD anchor distinct from USDT proxy | Live values, source IDs, units, four clocks, freshness and missing reasons |
| B Weekly | Existing PR Coinbase 260 completed weeks; Wilder RSI14, SMA50/200; TradingView INDEX comparison separate | Independent arithmetic tests, gap/unfinished week rejection, live result and scope |
| C ETF | Reuse btc_etf_intake, TFTC locked research role; 1/7/30 calendar and 5/20/60 session comparisons | Actual coverage, basket, freshness, hashes; BTC balance stays blocked without reliable BTC-unit history |
| D Onchain | Registered Coin Metrics MVRV; separately qualify realized cap, market cap history, MVRV Z, SOPR, Glassnode spot, CVDD and Pi Cycle | Formula/version/window and source rights; no ratio/Z substitution; no stale carry-forward |
| E Macro | Registered dollar, macro, rates, credit/liquidity families | Each family independently qualified with release and retrieval clocks |
| F Derivatives | Binance OI/funding/notional HTTP 451 confirmed; compliant authorized runtime or explicitly approved alternate scope | Live fresh observations, same venue/contract/units, no geographic restriction evasion |
| G Liquidation | Existing persistent collector and store; authorized continuously running environment | Both 1h and 24h coverage >=95%; no zero imputation, reconnect gaps visible |
| H L6 | Existing locked Coinbase/Bitstamp/Kraken and Binance archive capture | 201 completed consecutive UTC days and verified archive/checksum obligations; no substitute promotion |
| I Company | Strategy/Strive official filings, BTC/AFDS/debt/preferred claims/cash, CRT diluted mNAV and historical percentile, four health metrics, annual distribution burden | Same-time price and balance inputs, verified filing clocks, exact formula and historical sample; issuer gaps isolated |
| J Delivery | Public diagnostic index, existing Evidence Pack and handoff, private data excluded from public repository | Hash verified retrieval, freshness and independent family blockers; no artifact equated with ObservationStore |
| K PRE/POST | Doctrine 14, existing freeze_pre/freeze_post/revise_price_anchor | Actual two-task write/read receipt for same PRE ID/hash; original claims immutable; NY calendar and early close, 7–21 day pending |
| L Release | Offline regression plus real live acceptance, review and merge | No false green; partial research and formal readiness separate; no production or capital authorization |

External dependencies: lawful futures endpoint access, persistent collector host, source entitlement and verified shared PRE/POST storage. Do not declare these deployed merely because a PR exists. Public repository must not contain private portfolio or broker records. No new paid subscription or source authority change without approval.

Release evidence must identify commit SHA, CI run, test results, per-family state and remaining blockers. Earlier unverified numerical claims are not acceptance evidence.
