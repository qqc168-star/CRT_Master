# CRT BTC Season Router Recovery Gap Closure V0.1

## Status

- `STATUS = RESEARCH_VALIDATION_CANDIDATE`
- `FORMAL_SEASON_ROUTER_PROMOTION = BLOCKED`
- `FORMAL_MODEL_AUTHORITY = NONE`
- `FORMAL_WEIGHT_AUTHORITY = NONE`
- `FORMAL_THRESHOLD_AUTHORITY = NONE`
- `EXTERNAL_ACTION_AUTHORITY = NONE`

## Scope

This change closes only the research-validation gaps exposed by
`CRT_SEASON_ROUTER_RESEARCH_DELTA_20260822.md`.

It does not reconstruct missing historical wording, create a formal season
state machine, alter the six-layer model, or allow `candidate_score` to decide
BTC season.

## Added controls

1. The received Research Delta is stored byte-for-byte with its SHA-256 fixed
   by a compatibility test.
2. A research-only evidence-vector evaluator distinguishes:
   - attack observed but defensive pullback not tested;
   - pullback observed but Higher Low not confirmed;
   - Higher Low held but reattack/control-high break pending;
   - a closed price-structure control-transfer candidate;
   - a later lower-low invalidation.
3. Five historical/live case groups provide representative point-in-time
   checkpoints for 2018, 2019, 2022, 2023, and 2026.
4. No numeric price, date, duration, 200D distance, or swing-size threshold is
   created by the evaluator. It consumes already classified observations and
   fails closed on missing authority or impossible sequence order.

## Deliberate limits

- The cases are representative checkpoints, not a complete daily replay.
- Pivot discovery and the definition of a "meaningful" move remain outside
  machine authority.
- `CONTROL_TRANSFER_CANDIDATE` is research-only price-structure evidence. It
  is not `SE-WI-SPC`, `SE-SP`, Spring, or Bull confirmation.
- Cross-layer `C3`/`S2`/`S3`/`E2`/`E3`, independent later validation, vetoes,
  rollback, and adjacent-season transitions remain governed by the recovered
  V1.0 formal artifact and are not implemented here.
- Production approval remains unchanged and action output remains `NONE`.

## Remaining controlled gate

The formal Season Contract Semantic Mapping and Validator remains a separate
future gate. It must trace every executable rule to exact V1.0 clauses and
must not use this research evaluator as substitute formal authority.
