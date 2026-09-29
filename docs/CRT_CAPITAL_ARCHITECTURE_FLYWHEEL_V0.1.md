# CRT Capital Architecture & Flywheel V0.1

## Integration and authority

Base: `0579eed1320ad0fb3fb726107f509eba9ef13fb9` (PR #114 merged).
Branch: `codex/capital-architecture-flywheel-v01` in a new isolated worktree.
The N.S. Capital Posture Qualification Interface ruling resolves the initial
STOP: this is evidence synthesis for analyst review, never capital eligibility.

Current-main review found allocation, BTC Core, acquisition-route, health,
transition, valuation and Gold organs, but no equivalent capital synthesis.
The single new `capital_posture_context.py` consumes those outputs. No original
engine, Evidence Pack, Commander, formal Season or qualification is rebuilt.

| Existing owner | Reuse |
|---|---|
| deployment_posture_research_gate | Canonical translation and exact required downstream gate list, including blocked-input behavior |
| portfolio_allocation_context | Current allocation, BTC Core exclusion, strategic BTC/acquisition route and Company Health |
| Treasury Valuation Context | Read existing per-asset formal valuation context, without recalculating mNAV |
| Gold Research | Read hash-bound local next-cycle/convexity context, model dependencies and existing Assumption Watch results |
| Season/Transition | Preserve existing research, control-transfer references and evidence momentum; no new distance score |
| treasury_company_ct.validate_pit_replay | Reuse four-clock metadata validation for explicit capital research inputs |
| GPT/Commander closure | Reuse its authority scan; lines and plan/tranche qualification remain external |

The result has schema `CRT_CAPITAL_POSTURE_CONTEXT_V0.1`, storage `LOCAL_ONLY`,
and top-level state `BLOCKED` or `READY_FOR_ANALYST`. It always preserves:

```text
final_eligibility = NOT_DETERMINED
action_output = NONE
external_action_authority = NONE
capital_decision_authority = USER_ONLY
machine_execution = FORBIDDEN
production = NOT_APPROVED
machine_may_determine_btc_season = false
```

`AVAILABLE` for a downstream source means data is present, never that its gate
passed. Missing machine-reviewable claims are blocked. GPT judgment is
`NOT_EVALUATED`; user decision is `PENDING_USER_DECISION`. Commander lines and
plan/tranche binding are `EXTERNAL_TO_CONTEXT`. Neither absence blocks unrelated
capital research math. Unbound PASS flags are not consumed.

## Rails and evidence lanes

The local context preserves Spring 70/30 → 65/35 → 60/40 → 55/45, Summer 55/45
HOLD, analyst rollover 55/45 → 65/35 → 70/30 → 80/20, Autumn 80/20 preservation,
and Winter capital separation. Ratios mean Fixed/Growth, not MSTR/ASST.
55/45 is a maximum destination, not a quota. Qualified pullbacks, rollover and
harvest remain analyst-owned. Season names, price highs and calendar time never
advance the current step. Unknown current step is `BLOCKED`, never assumed HOLD.

The explicit current rail record requires user attribution, a matching cycle and
parent pack, valid four clocks and an unexpired research record. Validation of
that record means its provenance can be reviewed; it does not approve a trade.
The next path point is labeled only as a strategic destination. The canonical
NONE/SCOUT/BRIDGEHEAD/REINFORCEMENT candidate remains research-only and never
sets the recorded rail.

Legacy static allocation outputs remain upstream source material. This local
context does not use them as current rail or next destination. Any mismatch with
the explicit rail is shown as a contradiction. It does not silently rewrite the
existing pack or change the GPT bridge. The authoritative new rail semantics
are local analyst context under the N.S. ruling, not automatic replacement of
an upstream allocation or capital plan.

Harvest has two review lanes. Valuation readiness requires a usable existing
Treasury valuation or Gold next-cycle valuation for **each** MSTR and ASST;
optional convexity evidence and its missing state remain visible. Structure
readiness requires the existing canonical research evaluator/posture translation
bound to this parent pack. Both lanes contain original context or source hashes.
The readiness rule measures data availability only: even bearish or contradictory
research can be ready to read. It never confirms valuation realization, rollover
or harvest eligibility. Shared dependencies are retained; two lanes do not prove
two independent signals. Health disagreement remains separate from valuation.

## Capital calculations

- Operating capacity is 375 shares. The dollar anchor is 375 multiplied by an
  explicitly approved, current-cycle STRC/SATA equal-weight nine-month historical
  average. It requires complete coverage, source, sample period, method and expiry.
  This module consumes the approved aggregate rather than collecting prices or
  inventing an approval. $96.87 and $36,326.25 occur only as synthetic/example
  values, never production defaults. Each Winter requires a current-cycle record.
- BTC Opportunity Hurdle is `(expected winter BTC price / current BTC price) **
  (1 / years) - 1`; Flywheel Margin subtracts that hurdle from an explicit CRT
  forward CAGR scenario. Prices use USD; CAGR uses annual decimal returns. Missing,
  nonfinite or invalid inputs block the claim. No scenario return is guaranteed.
- Winter's gross research split consumes the existing tactical portfolio total,
  which excludes BTC Core. It shows the anchor, any shortfall and nonnegative
  residual for BTC accumulation. Residual is **not** spendable cash or an available
  tranche; liquidity, actual transfers and plan qualification remain external.
  Core never automatically returns to MSTR/ASST in Spring.
- Completed-cycle review reports BTC Core end minus start, 375-share capacity
  preservation, an attributed permanent-loss assessment, and supplied comparable
  cashflow-adjusted CRT/BTC realized CAGR. Missing components block separately.
  No loss judgment is inferred from price drawdown. These are review metrics.

Assumption drift reuses Gold's existing Assumption Watch output, with no second
evaluator. Scenario `assumption_ids` link to those records. A linked CHALLENGED
or INVALIDATED result blocks the current economics and removes its margin/hurdle
until recalculated. Unrelated assumptions do not veto that calculation. Missing
watch evidence is explicitly unknown, not an assumed validation. Maintenance
cadence is stored as doctrine: weekly, monthly, quarterly/10-Q, specified material
events, season transition and full-cycle overhaul; no scheduler is added.

## Local interface

From `radar` with `src` on `PYTHONPATH`:

```text
python -m crt_radar.capital_posture_context --input capital-input.json --evidence-pack existing-pack.json --gold-context gold-research.json --output capital-posture.json
```

The output must differ from every input path. The API is also a pure composer:
`build_capital_posture_context(inputs, evidence_pack, gold_context=None)`.
It neither mutates inputs nor writes anything unless the CLI output is requested.
It does not invoke GPT, collect data, send messages or execute a capital plan.

Top-level input requires `as_of_ms` and `cycle_id`. Optional claim inputs are
`current_rail`, `operating_anchor`, `flywheel_scenario`, `full_cycle_review`, and
canonical `research_evaluation` accompanied by `research_evidence_pack_hash`.
Pack hash and visibility are validated. Gold must have a valid context hash,
matching parent hash, visible as-of, LOCAL_ONLY storage and unchanged authority.
Missing or mismatched Gold blocks only Gold-dependent claims.

Each explicit capital record uses existing PIT metadata (`issuer_id=CAPITAL`,
`verification_state=VALIDATED`, `source_ref`, effective/disclosure/first-seen/
retrieval clocks and source semantic identity/version/validity), plus `metric_id`,
`cycle_id`, `basis_ref`, `limitation`, `invalidation`, and `valid_until_ms`.
Four clocks and expiry use epoch milliseconds. Hashes detect mutation/lineage;
they are not signatures, proof of source accuracy, user approval or eligibility.
The upstream owner must validate provenance before supplying VALIDATED records.

| Record metric | Additional fields |
|---|---|
| CURRENT_CAPITAL_RAIL | `recorded_by=USER`, matching `parent_evidence_pack_hash`, `rail`, explicit integer `step` (zero based) |
| OPERATING_PRICE_ANCHOR | `approval_ref`, method `EQUAL_WEIGHT_STRC_SATA_9M_AVERAGE`, `lookback_months=9`, assets STRC/SATA, USD currency, COMPLETE coverage, sample start/end milliseconds, `price_per_share_usd` |
| FLYWHEEL_SCENARIO | `scenario_only=true`, `assumption_ids`, `current_btc_price_usd`, `expected_winter_btc_price_usd`, `horizon_years`, `crt_forward_cagr` |
| FULL_CYCLE_REVIEW | `completed_cycle=true`, cycle start/end milliseconds, BTC Core start/end, ending operating capacity shares, permanent-loss boolean and assessment reference, realized CRT/BTC CAGR and same-period cashflow-adjusted basis reference |

Tests use synthetic data and existing producer fixtures. No current market
forecast, live allocation, approved historical price anchor, or user trade
decision is inferred by this delivery. Raw Capital/Gold output stays local:
the existing full bridge fixture remains 16,155 / 16,384 bytes, adding zero bytes.

## Validation

- Targeted capital / posture gate / allocation / Gold tests: 103 passed.
- Full regression: 973 passed, including 28 new capital synthesis tests.
- Python compileall, program registry and read-only surface checks: passed.
- Changes are confined to this module, its tests and this document. Existing
  engines, bridge payload, formal thresholds and execution surfaces are unchanged.
