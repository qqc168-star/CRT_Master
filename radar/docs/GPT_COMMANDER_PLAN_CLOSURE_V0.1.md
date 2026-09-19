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
