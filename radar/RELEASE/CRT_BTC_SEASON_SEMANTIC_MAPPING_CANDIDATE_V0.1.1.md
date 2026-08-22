# CRT BTC Season Semantic Mapping Corrected Candidate V0.1.1

## Decision

- Corrective delta build: `USER_APPROVED_CORRECTIVE_DELTA_2026-08-22`
- Engineering base: `f4e35d889cc2721b4ce785a1bd6c1d695a626e23`
- Candidate status: `SEMANTIC_MAPPING_CORRECTED_CANDIDATE_NOT_APPROVED`
- Exact mapping hash approval: `NOT_YET_APPROVED`
- Formal model: `NOT_APPROVED`
- Runtime binding: `NOT_APPROVED`
- Season output authority: `NONE`
- Production: `NOT_APPROVED`
- External Action Authority: `NONE`
- `action_output`: `NONE`

This corrected candidate supersedes V0.1 for exact-hash review. It does not
replace or modify the current fail-closed Season Router and exposes no Season
decision function.

## Corrective basis

The V0.1 exact-hash review was `BLOCKED` even though its tests passed. The
tests established byte stability and internal consistency, but the Chapter 7
crosswalk exposed an ambiguity that could collapse the stricter high-level
base route into the lower `S2 / E2` value-supported route. The review also
found formal macro-overlay, breakout/retest, output-contract, calendar and
data-quality surfaces that were not explicit enough for hash approval.

V0.1 canonical SHA-256
`9ddfa4137fff446403bca922274b6c95be27bd55b91db735745ba79e4948b965`
therefore remains unapproved and is superseded for review only. Its Git
history and its original files remain intact.

## Exact identities

- Formal archive SHA-256:
  `4556141b069596b24d78b8c4b5e19071f6b435f9748cd04891e91817e0a34c42`
- Working body SHA-256:
  `5ba963b51bcf49839299c3ce4e7649728d3d8caa05d8ca442691689e667f0064`
- Chapter 7 exact byte-slice SHA-256:
  `fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26`
- V0.1.1 candidate canonical SHA-256:
  `afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a`
- Deterministic validation-report SHA-256:
  `b4501884e8c91a8c5de19e37f161346e5666a1ca30e4af27966290aaa4e63cc9`

Recording the new canonical hash identifies this candidate for the next
review gate. It does not approve it.

## Corrected formal surface

V0.1.1 preserves the nine Season states, four output qualifiers and thirteen
declared transition edges from V0.1, and adds the missing explicit boundary:

- the value-supported Spring-candidate path is separate from the high-level
  base path;
- the high-level base path requires `V0`, `S3`, `E3`, persistent spot / CVD /
  institutional demand, leverage not leading spot, a recorded structural
  explanation, and route validation before candidate formation;
- `E2` can form only the standard Winter-to-Spring candidate; an untouched
  Realized Price or CVDD is not an automatic veto of a valid high-level base;
- `M+`, `M0`, `M-` and `MX` are mapped as a non-weighted Season overlay, not a
  seventh layer and never an independent Season declaration;
- breakout, hold, retest and demand-confirmation rules are preserved as
  symbolic-only contracts;
- all thirteen Chapter 7 formal output fields and the allowed conclusion
  vocabulary are cataloged without runtime assembly authority;
- calendar and fixed prices cannot trigger Season; Spring confirmation is not
  Summer or a full-exposure signal; emergency risk action does not update the
  Season label;
- all nine Chapter 7 data-quality invalidation conditions fail closed before
  formal transition.

All predicates and rules remain `SYMBOLIC_ONLY_NOT_RUNTIME_BOUND` or
`SCHEMA_ONLY_NOT_RUNTIME_BOUND`. They name formal requirements but do not
calculate them.

## Remaining unmapped blockers

Fourteen requirements remain explicitly `UNMAPPED_BLOCKED`:

1. Stage 3 equivalent-background classification;
2. formal runtime classifiers for V / C / S / E;
3. value-route classification and route-specific gate evaluation;
4. independent later-observation and event identity;
5. key weekly structure plus breakout / retest classification;
6. spot and institutional-demand persistence;
7. D0-D4 and VETO runtime classification;
8. macro-overlay and market-transmission classification;
9. last-valid-season bootstrap and persistence;
10. `SE-X` recovery and state lease;
11. non-Winter transition predicates;
12. formal source, freshness and clock bindings;
13. data-quality gate runtime evaluation;
14. formal output assembly and the Chapter 8 interface.

Two separate approval gates also remain closed:

- `AG_EXACT_MAPPING_HASH = NOT_YET_APPROVED`;
- `AG_RUNTIME_PROMOTION = NOT_APPROVED`.

No Research Delta item may fill, close or approve any blocker or gate.

## Files

- `CONFIG/BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1.json`
- `src/crt_radar/btc_season_semantic_mapping.py`
- `tests/test_btc_season_semantic_mapping.py`

The validator checks the exact formal source bytes, corrected candidate hash,
authority boundaries, constants, states, topology, split route predicates,
macro overlay, structure rules, output schema, data-quality rules, unmapped
requirements, approval gates and Research Delta firewall.

## Runtime boundary

The existing runtime remains unchanged:

- `season_router.status = SPEC_NOT_RECOVERED_CANDIDATE_FAIL_CLOSED`;
- `score_may_determine_btc_season = false`;
- `season = null`;
- `blocked_reason = V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED`.

Formal weights remain `20 / 20 / 17 / 25 / 13 / 5`, light thresholds remain
`-60 / -35 / 35 / 60`, and mNAV remains `Diluted Equity mNAV`.

## Verification

- Targeted semantic-mapping tests: `14 / 14 PASS`
- Full radar regression: `327 / 327 PASS`

Passing these tests establishes only corrected static mapping integrity and
fail-closed behavior. A separate exact-hash review and explicit user approval
are still required before any runtime-binding task may be considered.
