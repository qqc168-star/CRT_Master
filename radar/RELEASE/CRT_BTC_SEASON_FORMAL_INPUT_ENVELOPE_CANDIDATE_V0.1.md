# CRT BTC Season Formal Input Envelope Candidate V0.1

## Decision

- Status: `FORMAL_INPUT_ENVELOPE_CANDIDATE_NOT_APPROVED`
- Base current main: `cfc6da8ca80fc85059eac253ee99110855b78382`
- Candidate canonical SHA-256:
  `49510114f14a96707e2028875137fa5520f3360704bea5cbda7563c73a716073`
- Scope: formal input identity, freshness, quality and clock alignment only
- Formal model: `NOT_APPROVED`
- Runtime binding: `NOT_APPROVED`
- Season output authority: `NONE`
- Production: `NOT_APPROVED`
- External Action Authority: `NONE`
- `action_output`: `NONE`

## Purpose

This candidate establishes a fail-closed input envelope before any BTC Season
runtime classifier may consume Stage, V, C, S, E, D, macro, weekly structure,
spot demand, institutional demand, leverage or independent-validation inputs.

It implements only the part of the dependency review that can be expressed
without inventing a missing formal source responsibility matrix:

1. one envelope-level `as_of_ms` and decision-event identity;
2. source ID and pinned Source Registry hash per input;
3. observed, available and window clocks per input;
4. Q0-Q3 quality and freshness states;
5. explicit material-event clock-crossing detection;
6. deterministic fail-closed blockers.

## Deliberate incompleteness

All twelve required Season input families remain `UNBOUND_BLOCKED`. The active
`SOURCE_REGISTRY_V1.2.json` is pinned and verified as a partial engineering
dependency, but it is not promoted to complete Season source authority.

Therefore this candidate does not close:

`UM_FORMAL_SOURCE_BINDINGS_FRESHNESS_AND_CLOCK_ALIGNMENT`

It supplies the contract boundary required for a later, separately approved
formal source-responsibility mapping. Missing bindings cannot be filled by the
Research Delta, a candidate score, an inferred source, or a previous value.

## Runtime firewall

The validator:

- does not fetch or collect data;
- does not classify Stage, V, C, S, E, D, macro or price structure;
- does not import into `v110_candidate.py`;
- does not emit or persist Season;
- cannot approve runtime or Production;
- always reports `UNBOUND_BLOCKED` while the formal family bindings are absent.

No existing registry, semantic mapping, hash approval seal, runtime,
governance, weight, threshold, mNAV or Production file is modified.

## Files

- `CONFIG/BTC_SEASON_FORMAL_INPUT_ENVELOPE_CANDIDATE_V0.1.json`
- `src/crt_radar/btc_season_formal_input_envelope.py`
- `tests/test_btc_season_formal_input_envelope.py`

## Acceptance target

- Candidate contract and pinned identities validate exactly.
- Missing, stale, low-quality, future-clock, invalid-window, registry-mismatch
  and material-event-crossing inputs fail closed.
- Claimed formal bindings require a pinned registry source and still cannot
  override the candidate's `UNBOUND_BLOCKED` boundary.
- Runtime import remains absent.
- Full radar regression remains green.

## Verification

- Formal Input Envelope targeted tests: `11 / 11 PASS`
- Full radar regression: `347 / 347 PASS`
- Complete-shape candidate result: `UNBOUND_BLOCKED`
- Unbound required families: `12 / 12`
- Runtime import of this candidate: absent
- Season output: `BLOCKED / null`
