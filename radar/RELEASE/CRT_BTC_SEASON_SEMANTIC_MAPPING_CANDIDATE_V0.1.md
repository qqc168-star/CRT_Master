# CRT BTC Season Semantic Mapping Candidate V0.1

## Decision

- Candidate build: `USER_APPROVED_2026-08-22`
- Engineering base: `bd658a8813d8f0ce17a9a41efc62db13cae1c777`
- Candidate status: `SEMANTIC_MAPPING_CANDIDATE_NOT_APPROVED`
- Exact mapping hash approval: `NOT_YET_APPROVED`
- Formal model: `NOT_APPROVED`
- Runtime binding: `NOT_APPROVED`
- Season output authority: `NONE`
- Production: `NOT_APPROVED`
- External Action Authority: `NONE`
- `action_output`: `NONE`

This candidate does not replace or modify the current fail-closed Season
Router. It creates a deterministic compatibility validator for the accepted
CRT-BTC-001 V1.0 Chapter 7 source and a machine-readable inventory of what is
formally stated versus what remains semantically unmapped.

## Exact identities

- Formal archive SHA-256:
  `4556141b069596b24d78b8c4b5e19071f6b435f9748cd04891e91817e0a34c42`
- Working body SHA-256:
  `5ba963b51bcf49839299c3ce4e7649728d3d8caa05d8ca442691689e667f0064`
- Chapter 7 exact byte-slice SHA-256:
  `fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26`
- Candidate canonical SHA-256:
  `9ddfa4137fff446403bca922274b6c95be27bd55b91db735745ba79e4948b965`

The canonical hash identifies this candidate for review. Recording it does
not approve it.

## Mapped surface

The candidate maps only Chapter 7 semantics that are explicit enough to
preserve without inventing operational thresholds:

- the nine formal state identifiers;
- confirmed, candidate and exception state kinds;
- `SEASON_UNDER_REVIEW`, `CANDIDATE_FAILED`, `DATA_INCOMPLETE` and
  `DATA_CONFLICT` output qualifiers;
- candidate formation, later confirmation and candidate-failure topology;
- the specifically stated reviewed Spring-to-Winter rollback;
- candidate/confirmation event separation;
- independent later validation;
- adjacent-only normal transitions;
- candidate failure returning to the anchor season;
- confirmed-season review before rollback;
- score-is-not-season and latest-real-data safeguards;
- symbolic Winter-to-Spring candidate, confirmation, failure and rollback
  predicates.

Symbolic predicates preserve named upstream requirements such as `C3`, `S3`
and `E3`. They do not calculate those states and cannot route a season.

## Unmapped blockers

Twelve requirements remain explicitly `UNMAPPED_BLOCKED`:

1. Stage 3 equivalent-background classification;
2. formal runtime classifiers for V / C / S / E;
3. the independent later-observation window;
4. key weekly-structure identification;
5. spot and institutional-demand persistence;
6. D0-D4 and VETO runtime classification;
7. macro-transmission classification;
8. last-valid-season bootstrap and persistence;
9. `SE-X` recovery and state lease;
10. non-Winter transition predicates;
11. formal source, freshness and clock bindings;
12. exact mapping-hash and runtime-promotion approval.

No Research Delta item may fill or close any of these requirements.

## Files

- `CONFIG/BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.json`
- `src/crt_radar/btc_season_semantic_mapping.py`
- `tests/test_btc_season_semantic_mapping.py`

The module validates source bytes, candidate structure, authority boundaries,
formal constants, state topology, symbolic predicates, explicit unmapped
requirements and the research firewall. It exposes no transition-decision
function and is not imported by `v110_candidate.py` or `evidence_pack.py`.

## Runtime boundary

The existing runtime remains unchanged:

- `season_router.status = SPEC_NOT_RECOVERED_CANDIDATE_FAIL_CLOSED`;
- `score_may_determine_btc_season = false`;
- `season = null`;
- `blocked_reason = V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED`.

Formal weights remain `20 / 20 / 17 / 25 / 13 / 5`, light thresholds remain
`-60 / -35 / 35 / 60`, and mNAV remains `Diluted Equity mNAV`.

## Verification

- Targeted semantic-mapping tests: `10 / 10 PASS`
- Full radar regression: `323 / 323 PASS`

Passing this candidate's tests establishes only static mapping integrity and
fail-closed behavior. A later review and explicit approval of the exact
candidate hash are required before any separate runtime-binding work may
begin.
