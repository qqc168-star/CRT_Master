# Radar Closure & Company Health V0.1

## Stage 0 — integration review

Remote main verified with `git ls-remote origin refs/heads/main`:
`07f67840a87d64852bac039a3e7454006142e1cf` (2026-09-29 Asia/Taipei).
Canonical checkout is older (`ffb308a`); it is not the implementation base.
Isolated branch `codex/radar-closure-company-health-v01` starts at verified main,
and its git-common-dir resolves to the canonical CRT_Master/.git.

Reuse: Treasury CT's five organs, four-clock validation, comparison bases,
claim blockers and event accounting; existing common_equity_health, residual
calculation, Evidence Pack hash, and compact portfolio bridge projection.
Issuer adapters already extract source facts; they do not establish all the
comparison bases, usable cash or complete capital conversion consequences.
Those missing claims must remain blocked rather than be inferred from filings.

Confirmed gaps: _health_row reduces health to BTC/share and residual direction;
funding is not consumed; events have no trade-off synthesis; the bridge only
counts conversion events; CT-only packs do not create common_equity_health.

Minimal delta: one interpretation helper (no collection or fact store), small
CT extensions for comparable market absorption and explicit cash usability,
six independent health dimensions attached to the existing health row, observed
capital routes and claim-level uncertainty, and compact hash-bound projection.

Files to touch: treasury_company_ct.py, portfolio_allocation_context.py,
evidence_pack.py, new company_health.py, focused tests and this document.
Entry-point review also requires a small daily_evidence_runner.py pass-through
and optional CLI input, so the synthesis is reachable without allocation input.
The existing gpt_handoff call consumes the extended compact projection.
Explicitly untouched: season/router/input binding, weights/lights/mNAV formula,
Wake 90/95, issuer collectors, broker/transport authority, deployment research
gate, side-job/long-cycle rules, private state, existing worktrees and stashes.

No architectural conflict found. Gold Pack's four Markdown files and both
transcripts were reviewed. Source claims remain research, never issuer facts.
Forward 200WMA, BTC/Gold, liquidity models, convexity, seasonal rails and harvest
are excluded. No new source collection or source claim promotion is required.

Acceptance: synthetic Strategy can deteriorate per share/common efficiency/
liquidity while funding and senior burden improve; synthetic Strive can accrete
while senior claims/carry deteriorate. Mixed consequences remain MIXED with
analyst judgment required; unknowns stay null and block only their claims.
Incompatible bases, invalid/future metadata, superseded events and duplicate
observations cannot establish a direction or migration. No management scoring,
future capacity inference, season mutation or trade output. Compact bridge must
preserve dimensions/uncertainty and remain below 16,384 bytes; raw histories stay
local. Targeted tests precede full regression, compile and repository checks.

## Interpretation contract

Dimensions report observed changes, not a health score or trade signal. Direction
uses only IMPROVING / STABLE / DETERIORATING / BLOCKED. Opposing verified changes
use direction=BLOCKED and interpretation_state=MIXED, with an explicit reason
and analyst_judgment_required=true; complete evidence can remain AVAILABLE.
Unavailable comparisons use interpretation_state=INSUFFICIENT_EVIDENCE. PARTIAL
availability preserves known changes alongside explicitly missing claims.
Residual value retains the existing caller-supplied coherent scenario contract.
An observed capital route is not proof of a dominant or durable funding engine.
Emerging routes are candidates only; future funding capacity and management
intent are never inferred. Source duplication is not independent corroboration.

## Input and output wiring

`run_daily_evidence(..., treasury_company_ct_inputs={"MSTR": ct, "ASST": ct})`
and CLI `--treasury-company-ct-inputs <local.json>` accept existing normalized
CT inputs keyed by asset, including issuer_id and as_of_ms. Asset/issuer mismatch
is rejected. The Evidence Pack builder also accepts this batch form, retaining
its singular `treasury_company_ct_input` argument for compatibility; callers
cannot supply both. This is a local input artifact, not a new database.

After an official filing is validated and normalized through the existing CT
contract, both issuers flow into the existing asset_facts and
common_equity_health.assets.<asset>.company_health. No season or allocation input
is required. Filing snippets alone cannot establish comparison windows,
complete burden or cash usability: those claims remain BLOCKED. This release
does not deploy a live collector or fabricate normalization from missing data.

Optional CT extensions:

- Funding `absorption_comparison.previous/current`: normal CT metadata,
  `basis_ref`, equal positive `window_ms`, and verified `net_proceeds_usd`.
  Current effective time must match the funding instrument. The change measures
  observed primary funding absorption, not independent secondary-market demand.
  Cost uses existing previous_cost. Comparable usable-capacity history is still
  explicitly missing; higher authorized capacity is never a substitute.
- Burden `usd_cash_usable_for_carry=true` plus `cash_usability_basis_ref`:
  upstream attestation that cash is legally usable for carry. Comparative
  liquidity requires the same usability and coverage bases at both endpoints.
  Legacy cash calculations are preserved, but do not satisfy this new claim
  without the attestation. Coverage years are static, not a solvency forecast.

Each dimension contains direction, availability state, individual numeric
claims, supporting source refs and missing evidence. Mixed evidence remains a
separate interpretation, never STABLE, a fifth direction, a vote or net score.
Independent known claims survive incomplete
coverage. Residual comparisons reuse the existing coherent residual-input
contract and require aligned asset/burden endpoints; direction uses absolute
change so a negative starting residual does not reverse its economic meaning.
Common capital efficiency describes the per-share outcome during an interval
containing verified common issuance; it does not assert causal attribution.

Capital conversion lists individual consequences and contemporaneous per-share
outcomes. It never sums overlapping events or trades BTC against USD into a
score. Latest observed routes are current_engine; routes absent from earlier
observed events are emerging candidates. Both remain ANALYST_REQUIRED, with
dominance, future capacity and management intent expressly unestablished.
Management evidence remains in CT; no quality score is calculated.

Legacy health_direction retains its four-value enum. Opposing verified
dimensions or a MIXED interpretation make either legacy polarity BLOCKED with
MULTIDIMENSIONAL_TRADE_OFF_REQUIRES_ANALYST, preventing downstream health tilt.
Consistent known dimensions preserve the legacy direction; unknown claims do
not fabricate opposition. New partial claims do not erase independently valid facts.
Valuation and the existing allocation/season policies are separate.

Full provenance (four clocks and semantic binding), coverage, limitations,
invalidation and canonical SHA-256 stay local. The bridge verifies that hash,
then carries dimension direction/availability, interpretation/reason,
analyst_judgment_required and claim_scope, plus missing-claim examples/counts,
observed route examples/counts, contradictions and role-review requirements.
Funding scope is explicitly PRIMARY_FUNDING_ABSORPTION_AND_COST_ONLY; it does
not confirm independent secondary-market acceptance.
At most three missing-claim examples per dimension and four route examples are
shown; counts disclose additional local details. Raw events and histories stay
local and the existing strict 16,384-byte guard is unchanged.

## Deterministic scenarios

| Dimension | Synthetic Strategy | Synthetic Strive |
|---|---|---|
| Per-share asset engine | DETERIORATING | IMPROVING |
| Common capital efficiency | DETERIORATING | BLOCKED (no common issuance) |
| Funding / market acceptance | IMPROVING (partial) | IMPROVING (partial) |
| Senior claims / carry | IMPROVING | DETERIORATING |
| Liquidity buffer | DETERIORATING | DETERIORATING |
| Capital conversion | BLOCKED direction / MIXED interpretation | BLOCKED direction / MIXED interpretation |

These are synthetic accounting fixtures, not claims about current issuer
health. Research transcripts supply no factual inputs to these scenarios.

## Stage 2 validation record

On 2026-09-29, in the isolated worktree with Python 3.13.14:

- Targeted health/CT/portfolio/valuation/daily runner: 108 tests passed.
- Full unittest discovery: 912 tests passed (67.682 seconds).
- compileall for src/tests/scripts: passed.
- Program registry and read-only surface checks: passed.
- git diff --check: passed (only Git's existing CRLF conversion notices).
- Full bridge with both health contexts, portfolio context and two 2,100-day
  valuation histories: strict size acceptance passed; histories remain local.
- Remote main reverified unchanged at the stated baseline before sealing.

No live issuer data validation, broker operation, production deployment or
merge is represented by these results. Missing normalized official evidence
continues to block its own claims.

## N.S. architecture review corrections

Reviewed parent: ba79353124e7f3f40d20c2ec650db6e83d95e3f1.
The existing architecture is retained. Corrections are limited to the four-value
direction enum with separate MIXED interpretation, symmetric aggregate trade-off
blocking, and dimension-level analyst/scope warnings in the compact bridge.

Validation after corrections:

- Targeted health, CT, portfolio, portfolio wiring, valuation and GPT handoff:
  133 tests passed.
- Full regression: 917 tests passed.
- compileall, program registry, read-only surface and git diff --check: passed.
- Full bridge fixture (both health contexts, portfolio and two 2,100-day
  valuation histories): 16,155 UTF-8 bytes, strictly below 16,384. Funding scope
  and opposing-claim reason survive the actual bridge projection.
- Strategy and Strive aggregate/tilt cases also exclude conversion events to
  verify cross-dimension opposition independently of within-dimension MIXED.
- Uniform known directions preserve the legacy polarity; missing claims alone
  do not create a trade-off. Complete mixed evidence remains AVAILABLE while
  its direction is BLOCKED; incomplete mixed evidence remains PARTIAL.

No Season Router, Commander, formal mNAV, weight/light, transport authority,
Treasury engine or BUY/SELL changes. Submit the new commit on the same branch
for another N.S. Architecture Review; no PR or merge is part of this correction.
