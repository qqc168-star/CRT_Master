# CRT Gold Research & Treasury Valuation V0.1

## Current-main integration review

Remote main verified once at 17ed56365093d425a6fd4abfc6fc3d8bf3de7431.
New isolated worktree: .worktrees/gold-research-treasury-valuation-v01;
new branch: codex/gold-research-treasury-valuation-v01. git-common-dir resolves
to the canonical CRT_Master/.git. The previous room is closed.

Gold Pack's four Markdown files and both source transcripts are research input.
The present N.S. task supersedes the pack's generic stop-after-review / PR flow.
No transcript claim is promoted to a verified fact. Legacy 120K/135K/150K
scenarios remain research candidates, not forecasts, and are not removed.

| Surface on current main | Reuse / minimal delta |
|---|---|
| btc_transition_replay_evidence | Extend completed-week 200WMA with a labeled future path; reuse weekly validation and existing 200WMA calculation |
| Existing drawdown/envelope | Reuse as supplied long-horizon context; no new drawdown or season engine |
| External Structural Demand contract | Consume existing BTC_ETF_BALANCE_BTC, BTC_ETF_NET_FLOW_USD and BTC_ETF_FLOW_BREADTH IDs; add tracked public/official holdings in research only |
| institutional_flow / season_transition_warning_overlay | Preserve existing flow and regime outputs as references, without changing their classifications |
| L2/L3 and L4 | Preserve existing liquidity/leverage; add separate M2/TGA/RRP component observations without weights or scores |
| BTC acceptance/control transfer | Preserve existing evidence and authority; no new transition decision |
| mstr_asst_full_day_market_intake | Extend exact-close normalization with historical return sensitivity, with explicit source/window approval and split basis |
| Treasury CT / Treasury Valuation Context | Reuse verified BTC/share and its provenance; gross BTC-asset multiples remain a separate research lane |
| Company Health PR #113 | Read-only reference; no modification, replacement or health/convexity/valuation collapse |
| assumption_boundary_watch | Extend local external-assumption drift records; no formal price target |
| evidence_pack / gpt_handoff | Read existing pack references; no mutation or added bridge data |

New gold_research_context is a local research composer and input CLI, not an
Evidence Pack, collector, Treasury store or formal engine. It extends only the
missing research calculations; existing organs remain authoritative. The bridge
has only 229 bytes of fixture headroom, so all new output stays local. No warnings
are removed and the existing bridge is byte-for-byte unchanged for the same pack.

## Scope and acceptance

Forward 200WMA requires 200 consecutive completed visible weekly closes and a
future scenario frozen by the evaluation cutoff. BTC/gold requires an explicit
supply quantity and basis. Liquidity replay reports the complete fixed horizon
grid and predefined historical cohorts, not a selected best correlation, and
uses changes in log liquidity against future BTC returns at publication clocks.
Revision history without original availability evidence cannot pass PIT replay.

Institutional absorption uses a declared disjoint tracked universe, not a global
total. ETF episodes retain inventory, flow, breadth and recovery facts without
a stickiness score. PMI uses official normalized monthly observations, never a
peak trigger. Convexity uses exact equity-session BTC marks and a declared share
adjustment basis, never a hardcoded beta. Gross multiple distributions require
real observations and documented sample scope; manual 1.5/2/2.5 and
1.5/2.32/3.14 remain candidates, never medians. ASST remains lower confidence.

The next-cycle envelope keeps BTC price scenario, current BTC/share, factor,
gross multiple, source, as-of, sample period, confidence and limitation separate.
Formal Diluted Equity mNAV remains a referenced existing lane, never the name of
the gross BTC-asset ratio. Dependency descriptions expose shared BTC price,
liquidity and institutional inputs, with no averaging or independent-vote count.

All supplied observations retain source/provenance, four clocks, semantic/basis,
coverage, limitations and invalidation. Missing components block only their
claims. External hypotheses (including 340K +/-15%, 2026Q4–2027Q2) are stored
only as attributed Assumption Watch candidates; calendar time never triggers an
action. Production NOT_APPROVED, action/external authority NONE, capital
decision USER_ONLY and machine execution FORBIDDEN apply to all research output.

No change to Season Router/Input Binding, Commander, formal mNAV, six weights,
light thresholds, Wake 90/95, IBKR/transport, STRC/SATA rules or prior-room code.
No live data is fabricated to turn BLOCKED into AVAILABLE.

## Local use and input contract

From `radar`, with `src` on `PYTHONPATH`:

```text
python -m crt_radar.gold_research_context --input research-input.json --evidence-pack existing-pack.json --output gold-research.json
```

The CLI reads a hash-valid existing pack and writes a separate JSON sidecar. It
rejects an output path equal to either input. It does not collect data, schedule
work, publish a bridge or execute trades. `as_of_ms` is required and must be at
or after the parent pack's generation time. Omitted research inputs leave their
claims blocked; an omitted episode list is empty. The output binds the parent
hash and has its own deterministic context hash, without becoming an Evidence
Pack. Re-running identical inputs produces identical output.

Normalized history records use the existing Treasury PIT validation contract:
`issuer_id`, `effective_time`, `disclosure_time`, `first_seen_time`,
`retrieval_time`, `source_ref`, `verification_state=VALIDATED`, and
`source_semantic` (`identity`, `version`, `effective_from`, `effective_to`).
Clocks are UTC epoch milliseconds and must follow the existing clock ordering.
Research additionally requires `metric_id`, `source_class`, `coverage_state`,
`scope_ref`, `basis_ref`, `limitation`, and `invalidation`. A source label alone
is not verification: upstream intake must verify the supplied source and clocks.
Histories must retain one selected vintage per economic time and comparable
scope/basis/semantics. Macro/price/flow values are normalized USD; holdings and
circulating supply are BTC quantities. No currency or unit conversion is guessed.

| Input key | Required research binding |
|---|---|
| `forward_200wma` | Existing `weekly_bars`, `provenance`; `scenario` with ID, source, ISO timestamp `frozen_at`, and consecutive `weekly_path` points (`week_closed_at`, positive `close`). Historical weekly timestamps use the existing ISO completed-week contract. |
| `btc_gold` | Frozen scenario with explicit `btc_supply_basis`, `btc_supply_quantity`, `gold_market_cap_usd`, and `btc_gold_ratio`. |
| `liquidity` | M2/TGA/RRP normalized official arrays. M2 includes `period=YYYY-MM`; RRP additionally requires a validated sourced `RRP_calendar.expected_dates` with every published business day in each declared week. |
| `liquidity_replay` | `metric_id` M2/TGA/RRP, normalized `liquidity`, and `btc_prices` with exact visible endpoints. Fixed 4/8/12/26-week horizons and all predefined cohorts are retained, including omitted-pair reasons. |
| Parent `asset_facts.items` | Existing ETF metric IDs plus public-company and sovereign/official holdings; quantities require explicit `holding_scope_ids`. Totals require disjoint holders and aligned observation times. |
| `btc_circulating_supply` | Optional normalized BTC supply observation at the same time as the tracked holdings total. Missing supply blocks only the share-of-supply claim. |
| `etf_episodes` | IDs, sourced start/trough/end boundaries, approved market-window binding and BTC prices; validated complete `flow_observation_times` calendar. Inventory, price, flow and observed breadth remain separately available/blocked. |
| `pmi` | `PMI` and `PMI_NEW_ORDERS` official monthly arrays with `period=YYYY-MM`; gaps block slopes, not the known level. |
| `convexity` | Existing `equity_bars`/`btc_close_marks` plus validated `source_window_contract` containing source, availability, share-adjustment basis and every `expected_session_close_ms`. |
| `next_cycle.MSTR` / `.ASST` | `history` and labeled `scenarios`; current diluted BTC/share comes only from the unique matching Treasury Valuation Context fact in the parent. |
| `assumptions` | Attributed assumption ID/text/source/as-of/invalidation, optional reference value, PIT-valid observed reality and optional explicitly bound analyst assessment. Calendar time alone never invalidates a hypothesis. |

General frozen scenarios require `scenario_only=true`, `scenario_id`,
`frozen_at` in epoch milliseconds, `source_ref`, `limitation`, and `invalidation`.
Next-cycle scenarios additionally require `future_btc_price_usd`,
`btc_per_share_factor`, and either `multiple_kind=RESEARCH_SCENARIO_CANDIDATE`
with a numeric `gross_btc_asset_multiple`, or `HISTORICAL_DISTRIBUTION` with
`quantile` median/P75/P90 and `distribution` distribution/bull_window.

Historical gross-multiple input contains normalized issuer-specific
`observations`, `sample_definition`, and optional `bull_window_binding`.
Each observation binds exact-close equity/BTC prices, diluted BTC/share,
`market_window_lock_ref`, and comparable `share_basis_ref`. The verified sample
definition declares every expected observation time, complete coverage, start/end,
and `ALL_AVAILABLE_HISTORY` for MSTR or `POST_STRATEGY_POST_MERGER` for ASST.
The bull-window binding must be visible at its own window start and retain its
classification source; retrospective selection cannot become a PIT result.
Quantiles use linear interpolation at `(n-1)*p`. Two points are the mathematical
minimum, not evidence of statistical reliability; sample size and limitations
remain visible, with lower confidence for ASST.

Liquidity correlations use publication/locally visible vintages, never the
economic period as a substituted release clock. At least three pairs are needed
to calculate a descriptive correlation; overlapping horizons and small samples
do not establish significance, causality, or permission to promote thresholds.
RRP weekly values are means of daily stocks, not sums. Convexity uses daily
simple returns, covariance/variance beta, compounded upside/downside capture,
and equity-minus-BTC compounded return; its rolling windows are 20/60 sessions.

## Evidence status

Tests use explicitly synthetic fixtures to verify calculations, claim blocking,
clock discipline and reuse. This delivery does not assert that live MSTR/ASST
all-history distributions or macro vintages have been acquired or independently
verified. Those outputs remain blocked until their source contracts are supplied.
The pack's narrative prices and multiples remain attributed research candidates.

## Validation record

- Targeted Gold / weekly replay / exact-close intake / assumption watch: 63 passed.
- Full regression: 945 passed (including 28 new Gold tests).
- Python compileall, program registry and read-only surface checks: passed.
- Existing full bridge fixture: 16,155 bytes, below 16,384; Gold adds zero bytes.
- Scope remains six changed files, with no PR or merge in this delivery.
