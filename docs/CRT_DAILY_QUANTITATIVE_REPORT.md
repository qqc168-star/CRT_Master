# Daily PRE/POST quantitative report

This is a read-only presentation of the existing Evidence Pack, Treasury Company
CT, six-dimensional Company Health and immutable tactical PRE/POST records.
It implements the approved daily report fields without changing any formal
source, score, season, mNAV formula, capital rail, production or action authority.
It is not an automatic forecasting or delivery service, nor a complete 360/Q5
investment-reasoning acceptance. Missing inputs remain visible per claim.

## Existing capabilities and the composition gap

| Capability | Treatment |
|---|---|
| Source Gate, completed-week 50/200WMA, CT, Company Health, formal mNAV, PRE/POST | Reused |
| TFTC archive, declared fund universe and calendar | Reused; original 1D/7D/30D calendar summaries unchanged |
| 5/20/60 completed-session flow and preceding-period comparison | Added research composition on the same validated TFTC archive |
| FRED EFFR, DGS2, DFII10 and broad-dollar levels already fetched | Retained as non-scoring facts in existing `asset_facts.items` |
| Weekly RSI(14), weekly change and report formatting | Deterministic research presentation; no new classification rule |
| DXY, nominal 10Y, MVRV-Z, SOPR, account ratios or company-wide acquisition cost without qualified existing inputs | BLOCKED; no substitute provider or guessed value |

## Use

`crt_radar.daily_quantitative_report.build_report()` accepts a sealed Evidence Pack,
optional hash-linked local context and exported frozen PRE/POST records.
`build_report_from_store()` instead reads the original records through the
existing ObservationStore and `read_pre()` interfaces, without creating or
changing research events. No second database or schema is introduced.

Markdown presents eight investor-facing sections before the full quantitative
audit appendix: BTC overview (including macro), 1–3-week scenarios, weekly/on-chain,
ETF/spot demand, leverage, Strive's five health views, N.S. joint review, and
PRE/POST verification/invalidation. The joint-review slot remains NOT_RUN until
N.S. forms the judgment; the renderer does not invent it. Frozen PRE/POST originals
and linked PRE anchors/targets remain visible, not replaced by generated advice.

The local CLI only reads explicit input files and creates a new JSON/Markdown
report pair. Existing inputs/outputs are never overwritten:

```text
python -m crt_radar.daily_quantitative_report --evidence-pack <pack.json> --context <context.json> --output <new-report.json>
```

Optional `--forecast-record` and `--original-pre` accept the exact exported
records returned by the existing freeze/read APIs. An exported content hash
proves internal integrity, not database persistence, historical visibility or
analyst independence. Reports distinguish caller-provided records from actual
ObservationStore readback. A POST must retain its original PRE ID/hash. Source
clocks, original text, anchor, claims, expiry and review results are preserved;
the report never freezes, revises, matures or upgrades a prediction.

## Local context and provenance

Context must name the exact `evidence_pack_hash`.

- `sources`: existing PRE source references, including ID/reference, evidence hash,
  validation reference, quality and `observed_at_ms <= available_at_ms <=
  retrieved_at_ms <= validated_at_ms <= cutoff`. Market values come from the
  sealed pack, not arbitrary numbers in this list. Current observations also
  need upstream `valid_until_ms`; monetary quotes need explicit USD/USDT currency.
- `weekly_archive`: `raw_json` of the **existing normalized weekly-bar contract**
  plus its source reference. Verify parent raw archives using the existing intake
  before supplying the normalization; retain parent SHA-256 and normalization
  provenance in `source_evidence`. The JSON byte hash must match `evidence_hash`.
  Completed bars must have been visible at original acquisition, and the existing
  weekly loader rejects duplicates, gaps and wrong ordering. A later replay cannot
  complete a bar. Research RSI uses Wilder smoothing with an initial 14-change
  arithmetic mean; flat history is 50, a no-loss rising history is 100. Neither
  RSI nor WMA defines a formal season or complete KEY_WEEKLY_STRUCTURE.
  Each WMA and RSI displays the latest and preceding completed-week values and
  their arithmetic difference from this same acquisition-limited archive. RSI
  differences are index points, not percentage returns. Weekly close distances
  to 50/200WMA are percentages; stale sources stay STALE for all these values.
- `btc_etf_archive`: existing TFTC envelope, with the same hash already present in
  pack facts. Every 5/20/60-session comparison uses one constant fund scope over
  both nonoverlapping periods. Missing funds remain null in daily detail and are
  excluded from **both** totals, with PARTIAL coverage. No provider aggregate or
  Farside value fills a missing fund. Retrieval vintage is not proof of historical
  publication; unknown publication time remains unknown.
- `mnav_trial`: existing four-component mNAV input evidence, dilution basis and
  alignment state. Original source/dilution clocks remain attached. The existing
  formal calculator and the matching sealed CT valuation receipt are required
  for formal qualification; a standalone same-formula trial is not sufficient.
  Wrong asset/currency, blocked sources and missing raw hashes cannot support
  the research arithmetic either. Same-formula research
  substitution is explicitly separated when sources are usable only for research
  or effective dates differ; no formal receipt, history/CDF insertion or BUY
  permission is produced. Expired/unproven current-price validity cannot be
  displayed as a qualified current valuation.
- `btc_price_scenarios`: optional explicit research prices with `assumption_ref`.
  There are no default BTC thresholds. Research coverage is
  `(BTC holdings * BTC price + cash + STRC market value) / initial preferred claims`,
  not solvency, formal mNAV, dynamic liquidation claims or a trade trigger.
  Every component keeps separate source/clocks/qualification. Cash is the
  source-bound cash-and-equivalents total; Reserve is never added again. The
  denominator must explicitly represent complete **initial** preference, not an
  unspecified preferred balance. The source-bound CT observations must contain
  `reported_fields.initial_preferred_claims_usd` and
  `initial_preferred_claims_scope = COMPLETE_INITIAL_PREFERENCE` with original
  hash and existing CT clock validation. This projection does not create that
  fact from conditional offer terms or dynamic claims. Missing any necessary
  component blocks the named ratio instead of falling back to BTC-only. Price
  stress keeps the independently evidenced cash and STRC amounts unchanged.

Local input hashes do not certify external source truth. Existing intake/source
qualification remains necessary; a caller cannot certify a new formal source
by writing a quality label. All values retain sources, observation/publication/
retrieval clocks, units, basis, inputs and qualification in JSON. Markdown shows
the numeric table and clocks; UNKNOWN is not replaced by a guessed timestamp.

## Company time lines and limits

Company snapshots and the current market-price trial are different time lines.
BTC/share changes use exact 13/4/1-week (91/28/7-day) reference dates on a
comparable dilution/settlement basis; no nearest-date assumption or interpolation
is silently introduced. Missing references block only that comparison. Historical
mNAV uses the existing same-formula/same-scope comparison and prints three-decimal
levels such as `0.777`, without X or %. It is not a percentage change or a valuation
recomputed using today's price. Current mNAV displays all four actual substitutions:

`(diluted_shares * equity_price_usd) / (btc_holdings * btc_price_usd)`.
For a company snapshot ending 2026-10-23, references are 2026-07-24,
2026-09-25 and 2026-10-16. Calendar-month alternatives do not fill missing windows.

Existing CT handles Reserve/cash non-overlap, use qualifications, fixed payments,
financing stage, independent components and deployment attribution. The report
does not add reserve terms to reported cash, treat ATM capacity as proceeds,
sum overlapping financing periods, infer dynamic preferred claims or turn a
static carry coverage into survival runway. Six-dimensional Company Health
contradictions remain visible and do not become a new health score.

## Execution and acceptance boundary

There is no scheduler, market/SEC/broker fetch, GPT request, notification or trade
call in the report path. No Runtime, queue, store, PRE/POST original or governance
lock is modified. Cloud shared access remains `BLOCKED`, and actual cross-cloud
two-task read/write remains `NOT_RUN`. A synthetic regression PASS is not a real
market observation or investment-reasoning PASS. Historical real-source replays
must retain their actual local acquisition dates and cannot be called prospective
PREs or newly acquired current market evidence.
