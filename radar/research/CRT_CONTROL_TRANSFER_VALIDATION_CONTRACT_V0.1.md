# CRT CONTROL TRANSFER VALIDATION CONTRACT V0.1

Status: RESEARCH_ONLY_NOT_APPROVED

## Purpose

This contract defines the minimum post-C evidence required to move from:

`CONTROL_TRANSFER_CANDIDATE`

to the research-only state:

`CONTROL_TRANSFER_VALIDATED`

It does not define or approve Formal Season.

## First principles

1. Candidate and validation must be different events.
2. Validation is event-sequence based, not day-count based.
3. No fixed day, percent, or BTC-price threshold is allowed.
4. The old control zone and candidate invalidation anchor must be frozen at C.
5. A later adverse test may hold the old control zone directly or breach and reclaim it.
6. Candidate structure must remain preserved.
7. Renewed expansion is required.
8. A new local control-high break is strengthening evidence only, never a mandatory gate.
9. A validated control transfer may later move to UNDER_REVIEW or REVERSED.
10. Historical validation does not become a permanent bull certificate.

## Minimum evidence contract

Candidate:
- `state = CONTROL_TRANSFER_CANDIDATE`
- `event_id`
- `timestamp`
- `old_control_zone_ref`
- `candidate_invalidation_anchor_ref`
- `reference_provenance`

Post-C independent test:
- `event_id`
- `timestamp`
- `event_order = AFTER_CANDIDATE | UNRESOLVED`
- `distinct_event = true | false`
- `old_control_zone_result = HELD | BREACHED_AND_RECLAIMED | LOST_NOT_RECLAIMED | UNRESOLVED`
- `candidate_structure_result = PRESERVED | INVALIDATED | UNRESOLVED`
- `renewed_expansion = CONFIRMED | NOT_CONFIRMED | UNRESOLVED`
- `new_local_control_high_break = CONFIRMED | NOT_CONFIRMED | UNAVAILABLE`

Optional post-validation review:
- `state = NONE | UNDER_REVIEW | REVERSAL_CONFIRMED`
- if state is not NONE: a distinct later event is required.

## Research output

- `VALIDATION_PENDING`
- `CONTROL_TRANSFER_VALIDATED`
- `CONTROL_TRANSFER_CANDIDATE_FAILED`
- `INCONCLUSIVE`
- `BLOCKED`

If validated, `current_validation_status` may be:
- `ACTIVE`
- `UNDER_REVIEW`
- `REVERSED`

## Mandatory governance locks

- `formal_season = None`
- `formal_model_authority = NONE`
- `formal_weight_authority = NONE`
- `formal_threshold_authority = NONE`
- `season_transition_authority = NONE`
- `machine_may_determine_btc_season = false`
- `machine_may_confirm_bull_transition = false`
- `action_output = NONE`
- `external_action_authority = NONE`
- `external_action_performed = false`

## Historical red-team intent

Acceptance set:
- 2015 successful reclaim -> VALIDATED / ACTIVE
- 2020 Q4 successful continuation -> VALIDATED / ACTIVE
- 2023 March successful reclaim -> VALIDATED / ACTIVE
- 2022 March failed control transfer -> CANDIDATE_FAILED
- 2021 Q4 -> VALIDATED first, later REVERSED
- 2020 February -> provisional research reference only; not eligible as a formal C acceptance case

## Explicit non-goals

This contract does not:
- detect pivots
- decide whether a move is meaningful
- create thresholds
- change Season semantics
- change weights
- change mNAV semantics
- create trade actions
- create capital authority
