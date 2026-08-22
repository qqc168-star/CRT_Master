# CRT L4 OI Point-in-Time Revision Policy V0.1

## Decision

- Status: `ENGINEERING_CANDIDATE_NOT_APPROVED`
- Base current main: `3d40a230f1cea08c253f0dafaa5f3a15ad876cb8`
- Policy canonical SHA-256:
  `41894ff01877da4fd7a0baf9aefcb783110129ab194350bd6c6696278f7c357e`
- Exact policy hash approval: `NOT_YET_APPROVED`
- Formal model: `NOT_APPROVED`
- Runtime binding: `NOT_APPROVED`
- Production: `NOT_APPROVED`
- Season output: `BLOCKED / null`
- External Action Authority: `NONE`
- `action_output`: `NONE`

## Purpose

The existing append-only ObservationStore can retain more than one L4
open-interest row for the same source observation timestamp. Before this
candidate, change baselines and the V1.10 candidate history either consumed all
duplicates or selected a database row without an availability clock.

This candidate makes those reads point-in-time deterministic without deleting
evidence or inventing a preferred value.

## Locked resolution contract

| Contract item | V0.1 rule |
|---|---|
| Observation identity | `input_family + metric + as_of_ms` |
| Availability proxy | CRT `recorded_at_ms` |
| Visibility | `recorded_at_ms <= evaluation_at_ms` |
| Selected revision | Greatest visible `recorded_at_ms` |
| Same-release tie | `AMBIGUOUS_REVISION_BLOCKED` |
| Future revision | Invisible until its recorded time |
| Source identity | Pinned `AS-L4` Source Registry source only |
| Raw retention | Append-only; distinct revisions remain auditable |
| Baseline input | One resolved row per `as_of_ms` |

No row order, value magnitude, evidence-hash lexical order, zero fill,
forward fill, source substitution, deletion or in-place overwrite may resolve a
tie.

## Scope

The policy applies only to:

- `OPEN_INTEREST.open_interest_contracts`;
- `OPEN_INTEREST_NOTIONAL.open_interest_notional_usd`;
- `OPEN_INTEREST_NOTIONAL.oi_to_market_cap_pct`.

The pinned sources are verified against canonical
`CONFIG/SOURCE_REGISTRY_V1.2.json`. Registry canonical identity is stable across
LF and CRLF checkouts.

## Integration

- `ObservationStore` retains its raw append-only audit series and adds an
  explicit visibility-clock resolver.
- Legacy latest lookup for a scoped OI metric fails closed unless the caller
  supplies `visible_at_ms`.
- `change_engine.py` uses the resolved series for horizon lookup and historical
  magnitude baselines.
- `v110_candidate.py` uses the same resolved series for L4 OI percentile
  history and records the policy identity in candidate output.
- `evidence_pack.py` passes its generation clock as the evaluation instant and
  blocks the pack if revision history is ambiguous or invalid.

## Deliberate incompleteness

This candidate does not certify the existing L4 historical dataset, repair a
gap, create provider publication timestamps, or prove that a historical
backfill was available before CRT first recorded it. `recorded_at_ms` remains a
conservative engineering availability proxy; it may not be backdated.

Therefore this work closes the deterministic duplicate-selection code gap, but
it does not by itself make L4 history formally sufficient or approve V1.10,
Production, runtime binding, BTC Season, a trading action, or a capital
decision.

## Files

- `CONFIG/L4_OI_POINT_IN_TIME_REVISION_POLICY_V0.1.json`
- `src/crt_radar/oi_revision_policy.py`
- `src/crt_radar/observation_store.py`
- `src/crt_radar/change_engine.py`
- `src/crt_radar/v110_candidate.py`
- `src/crt_radar/evidence_pack.py`
- `tests/test_l4_oi_point_in_time_revision_policy.py`
- integrated regression updates under `tests/`

## Verification

- L4 OI policy targeted tests: `9 / 9 PASS`
- Full radar regression: `366 / 366 PASS`
- Raw revisions retained: `PASS`
- Future revision invisibility: `PASS`
- Latest visible revision selection: `PASS`
- Same-release ambiguity rejection: `PASS`
- Source substitution and backdating rejection: `PASS`
- Change baseline one-row-per-timestamp resolution: `PASS`
- V1.10 candidate history resolution: `PASS`
- Evidence Pack ambiguity propagation: `BLOCKED`
- Formal score: `null`
- Season output: `BLOCKED / null`
- External action: `NONE`
