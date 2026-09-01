# Source Responsibility Matrix

## Engineering registry identity

This matrix is derived from `CONFIG/SOURCE_REGISTRY_V1.2.json`. The filename is retained for compatibility; the payload is the authority for registry identity and version.

| Field | Current value |
|---|---|
| Registry ID | `CRT-RADAR-SOURCE-REGISTRY-V1.4-WIP` |
| Payload version | `1.4-wip` |
| Status | `CANDIDATE_UNMERGED` |
| Registered sources | `12` |
| Production profile | `READ_ONLY_DECISION_SUPPORT` |
| External action authority | `NONE` |

## Registered engineering sources

| Namespace | Input family | Source ID | Parser ID | Criticality | Max age (seconds) | Scope / authority boundary |
|---|---|---|---|---|---:|---|
| `AS-L2` | `DOLLAR_STRENGTH_PROXY` | `CRT-CONN-FX-FRED-BROAD-USD-PROXY-001` | `FRED_LATEST_CSV_V1` | `CRITICAL_FAIL_CLOSED` | `864000` | Nominal Broad U.S. Dollar Index proxy; must never be labelled DXY. |
| `AS-L4` | `OPEN_INTEREST` | `CRT-CONN-BTC-DERIV-BINANCE-OI-001` | `BINANCE_OI_V1` | `CRITICAL_FAIL_CLOSED` | `300` | BTCUSDT perpetual open interest. |
| `AS-L4` | `FUNDING_RATE` | `CRT-CONN-BTC-DERIV-BINANCE-FUNDING-001` | `BINANCE_FUNDING_V1` | `CRITICAL_FAIL_CLOSED` | `32400` | BTCUSDT perpetual funding rate. |
| `AS-L4` | `LIQUIDATION_CONNECTIVITY_PROBE` | `CRT-CONN-BTC-DERIV-BINANCE-LIQ-PROBE-002` | `BINANCE_FORCE_ORDER_V1` | `DIAGNOSTIC_ONLY` | `120` | Connectivity probe only; metric authority is `NONE`. |
| `AS-L4` | `LIQUIDATION_AGGREGATES` | `CRT-CONN-BTC-DERIV-LIQ-AGGREGATOR-001` | `CRT_LIQ_AGGREGATE_SNAPSHOT_V1` | `CRITICAL_FAIL_CLOSED` | `120` | Verified local snapshot; live-shadow formal authority is `NONE`. |
| `AS-L1` | `MACRO_CONTEXT` | `CRT-CONN-MACRO-FRED-CONTEXT-001` | `FRED_MACRO_CONTEXT_V1` | `CRITICAL_FAIL_CLOSED` | `4000000` | Current macro evidence with locked candidate formulas; not a formal Season binding. |
| `AS-L2` | `RATES_CONTEXT` | `CRT-CONN-RATES-FRED-CONTEXT-001` | `FRED_RATES_CONTEXT_V1` | `CRITICAL_FAIL_CLOSED` | `864000` | Twenty-trading-day USD and rates engineering evidence. |
| `AS-L3` | `CREDIT_LIQUIDITY_CONTEXT` | `CRT-CONN-CREDIT-LIQUIDITY-CONTEXT-001` | `CRT_CREDIT_LIQUIDITY_CONTEXT_V1` | `CRITICAL_FAIL_CLOSED` | `864000` | Stablecoin and high-yield credit context; official ETP history remains separately fail-closed. |
| `AS-L4` | `OPEN_INTEREST_NOTIONAL` | `CRT-CONN-BTC-DERIV-BINANCE-OI-NOTIONAL-001` | `BINANCE_OI_NOTIONAL_V1` | `CRITICAL_FAIL_CLOSED` | `900` | Open-interest notional for leverage normalization. |
| `AS-L5` | `ONCHAIN_VALUE` | `CRT-CONN-BTC-ONCHAIN-COINMETRICS-COMMUNITY-001` | `COINMETRICS_MVRV_COMMUNITY_V1` | `NONCRITICAL_DISCLOSE_MISSING` | `172800` | Formula-transparent MVRV and NUPL engineering inputs. |
| `AS-L6` | `PRICE_STRUCTURE_CONTEXT` | `CRT-CONN-BTC-SPOT-PRICE-STRUCTURE-PROXY-001` | `BINANCE_PRICE_STRUCTURE_PROXY_V1` | `CRITICAL_FAIL_CLOSED` | `172800` | Directional proxy only; formal composite authority is `NONE`. |
| `AS-L3` | `BTC_SPOT_PRICE` | `CRT-CONN-BTC-SPOT-BINANCE-WAKE-001` | `BINANCE_SPOT_TICKER_24H_V1` | `NONCRITICAL_DISCLOSE_MISSING` | `120` | Operational wake-up only; formal metric and investment-threshold authority are `NONE`. |

Presence in this engineering registry does not grant Production, formal scoring, runtime binding, or Season-output authority.

## Candidate runtime source overlay

`CONFIG/IBKR_EQUITY_SOURCE_V0.1.json` adds `CRT-CONN-EQUITY-PREMARKET-IBKR-001` only at runtime, after preserving and recording the base registry hash. This prevents the IBKR experiment from mutating the sealed base registry identity. The overlay binds local TWS API L1 streaming plus 5-second `TRADES` bars for MSTR, ASST, STRC, and SATA. Delayed data, regulatory snapshots, account/order surfaces, machine execution, and capital-decision authority are forbidden.

`CONFIG/MSTR_ASST_MARKET_HEALTH_SOURCE_V0.1.json` separately declares five fail-closed Market Health inputs: IBKR daily equity bars, Binance exact-equity-close BTC marks, IBKR limited-covered-contract options observations, official issuer BTC-per-diluted-share facts, and explicitly approved Three-Army Commander lines. The first four now have live evidence: option aggregate call/put volume comes from underlying generic tick 100, while selected nearest-expiry contract OI/IV preserves its delayed field state and unavailable per-contract volume remains explicitly blocked rather than zero-filled. Approved line bundles remain pending and must block `latest.json`; simulation lines must never be promoted to approved lines.

## Formal BTC Season source gaps

The formal input envelope remains the binding-status authority. Every required family below is still unbound; engineering context with a similar name does not satisfy the formal source, transform, window, state, or independent-validation contract.

| Formal input family | Binding status | Remaining source / contract gap |
|---|---|---|
| `SEASON_STAGE_BACKGROUND` | `UNBOUND_BLOCKED` | Formal Stage producer, observation window, and persisted state are not bound. |
| `VALUE_STATE_V` | `UNBOUND_BLOCKED` | Formal value-state producer and exact Chapter 3 transform are not bound. |
| `CAPITULATION_STATE_C` | `UNBOUND_BLOCKED` | Formal capitulation-state producer and exact Chapter 4 transform are not bound. |
| `STOPPING_STATE_S` | `UNBOUND_BLOCKED` | Formal stopping-state producer and exact Chapter 5 transform are not bound. |
| `EVIDENCE_CONSISTENCY_E` | `UNBOUND_BLOCKED` | Formal consistency-state producer and cross-family window are not bound. |
| `CONFLICT_SEVERITY_D` | `UNBOUND_BLOCKED` | Formal conflict-severity producer and Chapter 6.8 transform are not bound. |
| `MACRO_OVERLAY_M` | `UNBOUND_BLOCKED` | Engineering macro context is not the formally bound four-state overlay producer. |
| `KEY_WEEKLY_STRUCTURE` | `UNBOUND_BLOCKED` | Formal weekly structure, breakout, hold, and retest producer is not bound. |
| `SPOT_DEMAND_QUALITY` | `UNBOUND_BLOCKED` | A formal multi-source spot-demand-quality transform is not bound. |
| `INSTITUTIONAL_SPOT_DEMAND` | `UNBOUND_BLOCKED` | Official institutional / ETP history and formal transform are not bound. |
| `LEVERAGE_COMPATIBILITY` | `UNBOUND_BLOCKED` | Formal leverage-compatibility transform across OI, funding, and liquidation evidence is not bound. |
| `INDEPENDENT_VALIDATION_EVENT` | `UNBOUND_BLOCKED` | Independent validation source, observation window, and event semantics are not bound. |

## Fixed governance boundary

- No source in this matrix has account, order, email, webhook, or fund-movement authority.
- This matrix does not change six-layer weights, thresholds, or mNAV semantics.
- Missing, stale, conflicting, or formally unbound evidence must fail closed.
- Runtime binding, Production approval, and Season output remain not approved.
- `action_output` remains `NONE`; External Action Authority remains `NONE`.
