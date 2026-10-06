# GPT -> Commander Plan closure V0.1

This local API closes the path from GPT-authored observation levels to the
existing bounded IBKR observation operator. It neither generates trading levels
nor grants capital eligibility. Production remains NOT_APPROVED.

## Source and judgment contract

Call `build_commander_source_bundle` with the original, independently verified
`source_main_sha`, current Evidence Pack V0.2, the ready result from
`run_gpt_handoff_gate`, the canonical research evaluation, and Work B posture
gate result. Bind the SHA of the checkout that produced the evidence; never
relabel an old bundle with a newly fetched main. The bundle is local provenance,
not a signature. It contains the original evidence and must remain local; use
the existing minimized GPT handoff for external transport if separately enabled.

The builder checks the evidence and handoff seals and linkage, recomputes Work B
from its research evaluation, and preserves all governance restrictions. The GPT
response must reference the resulting `bundle_hash` as `source_bundle_hash`.

A judgment has exactly these fields:

- `schema_version`: `CRT_GPT_COMMANDER_JUDGMENT_V0.1`
- `state`: `READY_FOR_VALIDATION`
- `judgment_id`, `asset`, `generated_at`, `valid_until`
- `source_main_sha`, `source_bundle_hash`, `posture_candidate`
- `lines`, `governance`

Times must have timezones. The four lines are ATTACK, FIRST_DEFENSE, INVALIDATION
and HARVEST. Each has exactly `line_id`, `line_type`, `price`, `direction`,
`btc_condition`, `confirmation_condition`, and `rationale`. GPT supplies these
values; the bridge never infers prices or substitutes missing context. The
existing Commander validator checks the line identities, prices and directions.
Context remains analyst-owned text for reanalysis, not a machine trade condition.

Judgment governance must equal:

```json
{
  "action_output": "NONE",
  "machine_execution": "FORBIDDEN",
  "external_action_authority": "NONE",
  "capital_decision_authority": "USER_ONLY",
  "production": "NOT_APPROVED"
}
```

## Validation, sealing and observation

```python
candidate = build_candidate_commander_plan(
    judgment, source_bundle=bundle, current_main_sha=verified_main_sha,
)
valid, blockers = validate_candidate_commander_plan(
    candidate, judgment, source_bundle=bundle, current_main_sha=verified_main_sha,
)
sealed = seal_candidate_commander_plan(
    candidate, judgment, source_bundle=bundle, current_main_sha=verified_main_sha,
)
```

Candidates are unsealed until validation succeeds. The validator reconstructs
Work D facts from the source evidence and machine market handoff, compares the
selected asset's critical facts/readiness, and rechecks live price freshness
using the existing source max-age policy. Supporting-fact gaps remain visible
without falsely blocking the critical core. Unknown schemas/states, altered
lineage, unavailable critical facts, future/expired windows, and authority
violations fail closed with `CommanderPlanBlocked`.

Use `run_gpt_commander_observation` with the same judgment, bundle, independently
rechecked current-main SHA and the existing operator configuration/runtime paths.
It rebuilds, validates and seals immediately before delegating to
`run_gate6c3_operator`. Failure occurs before feed construction, arming or runtime
writes. The existing LevelEventEngine, CommanderPlanAdapter, observation bridge,
observation journal and reanalysis handoff remain responsible for monitoring.
This module introduces no broker order, position, account or funds interface.

Work B still reports `RESEARCH_POSTURE_CANDIDATE`, `final_eligibility =
NOT_DETERMINED`, and its unchanged downstream gates. The candidate preserves
posture effects, including HOLD_OR_REVIEW_ONLY_NO_UPGRADE. A NONE posture cannot
arm this path. A valid non-NONE posture permits only the observation workflow;
it does not satisfy USER_DECISION, authorize a tranche, or promote formal Season.
Prices reaching a line only wake GPT reanalysis. No production approval, six-layer
weight, light threshold, mNAV semantic or external-action authority is changed.

The offline tests exercise the real operator with a fake market feed. They do
not start a brokerage connection or establish trading/production readiness.

## Responses structured judgment transport

`gpt_transport_worker` accepts `--source-bundle`, `--current-main-sha`, `--asset`
with `--event-id` to opt into structured judgments. All four are required together.
The caller must independently verify GitHub main; the worker does not relabel
source evidence or fetch Git. The local bundle is validated and its canonical
minimized Bridge must exactly equal the selected outbox payload before any send.
Only that Bridge and four binding identifiers are sent, never the local bundle.

The Responses adapter uses native `text.format` / `json_schema` / `strict: true`.
Its schema is a projection of the existing judgment constants in this module.
The context binds main SHA, bundle hash, requested asset and posture; no parser
fills in a price, reason, condition or evidence. Legacy smoke delivery remains
unchanged when the structured mode is not selected. The same model, 1,800 output
tokens, one attempt, no automatic retry and 16,384-byte input ceiling apply.
The new input wrapper and binding identifiers count toward that input ceiling.

The worker saves the complete provider JSON object under `responses/<event>.json`
before interpreting its content, including refusal/incomplete output. Successful
structured delivery additionally saves `judgments/<event>.json` containing the
unaltered parsed judgment, request/response hashes and an **unsealed** candidate.
Completion requires the existing Commander validator, not just JSON compliance.
Duplicate JSON keys, non-finite numbers, unknown fields, wrong lineage, requested
asset mismatch, invalid lines, refusal and incomplete responses fail closed.
Persisted send intent prevents a retry from resending an invalid or ambiguous
result. A saved candidate still requires fresh validation before observation;
transport never arms a monitor or performs a capital action.

Validation time is checked after the response arrives. A delayed response can
therefore fail the existing live-price freshness policy. Duplicate attempts may
also fail freshness on a later invocation, but cannot cause another provider call.
The original provider object is retained as JSON audit evidence, not a byte-for-
byte HTTP archive; response headers and credentials are never persisted.

These offline tests prove parsing/Commander validation and worker persistence,
not successful live inference. Worker protocol tests isolate the Bridge projection
with an explicit stub while retaining real source and Commander validators.
The full synthetic source-bundle projection has a separate over-budget rejection
test. A full live bundle exceeding 16 KiB remains a #8 blocker; it is not trimmed
here to produce a successful test. Provider capability for the fixed smoke model,
fresh market evidence and an actual accepted live response remain live-acceptance
requirements. There is no model migration or new production approval.

## Capital recommendation boundary (proposal only)

The existing four lines are observation thresholds and reanalysis context. They
cannot express an entire BUY/SELL/HOLD/WAIT/ROTATE capital recommendation, budget
or quantity. Do not overload line types, seal a recommendation as a Commander
plan, or interpret delivery as user approval.

If separately authorized later, the minimum independent recommendation record
would reference `source_main_sha`, `source_bundle_hash`, `judgment_id` (optional
when no observation lines apply), `asset`, `generated_at`, `valid_until`, and the
capital-state evidence hash/as-of. It would contain the analyst's proposed action,
conditions, rationale, opposing evidence and explicit missing-input blockers.
Quantity, currency, amount, reference/trigger price, fees and calculation basis
must be nullable together when not supported; a null amount is not zero. ROTATE
must identify both asset legs without treating expected proceeds as settled cash.
Authority stays USER_ONLY / NONE / NOT_APPROVED. This is a proposed data boundary,
not a new implemented schema, inference engine, allocation plan or trade permit.
