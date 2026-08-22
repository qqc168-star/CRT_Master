# CRT BTC Season Semantic Mapping Hash Approval Seal V0.1

## Decision

- Approval date: `2026-08-22`
- Approval actor: `CRT_OWNER_USER`
- Approval evidence: `EXPLICIT_USER_APPROVAL_2026-08-22`
- Seal status: `EXACT_MAPPING_HASH_APPROVED`
- Closed gate: `AG_EXACT_MAPPING_HASH`
- Formal model: `NOT_APPROVED`
- Runtime binding: `NOT_APPROVED`
- Season output authority: `NONE`
- Production: `NOT_APPROVED`
- External Action Authority: `NONE`
- `action_output`: `NONE`

The user explicitly approved the exact BTC Season Semantic Mapping Candidate
V0.1.1 canonical hash. This seal records that approval outside the hashed
candidate so the approved candidate identity does not change as a side effect
of recording approval.

## Approved immutable identity

- Mapping ID:
  `CRT-BTC-SEASON-SEMANTIC-MAPPING-CANDIDATE-V0.1.1`
- Candidate path:
  `CONFIG/BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1.json`
- Candidate commit:
  `744ac4341c02229b1a1d7a4954a4c4d253b86265`
- Candidate base current main:
  `f4e35d889cc2721b4ce785a1bd6c1d695a626e23`
- Candidate PR: `#32`
- Approved mapping canonical SHA-256:
  `afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a`
- Candidate validation-report SHA-256:
  `b4501884e8c91a8c5de19e37f161346e5666a1ca30e4af27966290aaa4e63cc9`
- Formal Chapter 7 SHA-256:
  `fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26`
- Approval-seal canonical SHA-256:
  `6af3c17c263df8b4434e85078e95b9d506f6efb19acb484ac39745355322f75a`
- Approval validation-report SHA-256:
  `22cfa653fae3759ea1bcfc82858c39ff74ac10a8a98f633757b8081cc9c22385`

## External-seal rule

The approved candidate JSON remains unchanged. Its embedded
`NOT_YET_APPROVED` values are preserved as part of the exact pre-approval
artifact whose canonical hash was reviewed. Effective exact-hash approval is
established only when all of the following validate together:

1. the unchanged V0.1.1 candidate canonical hash;
2. the exact formal Chapter 7 source bytes;
3. this external approval seal and its canonical hash;
4. the fail-closed approval validation report.

Changing the candidate, seal identity, approved hash, approval scope, Research
Delta firewall, or authority boundary invalidates the seal.

## Remaining blockers

The valid seal closes only `AG_EXACT_MAPPING_HASH`. It deliberately leaves:

- all fourteen semantic-mapping requirements as `UNMAPPED_BLOCKED`;
- `AG_RUNTIME_PROMOTION = NOT_APPROVED`;
- `runtime_binding_ready = false`;
- `machine_may_determine_btc_season = false`;
- `season = null`.

The separate Research Delta has no authority to approve a hash or runtime,
close a blocker, supply a formal state or rule, alter weights or thresholds,
or change this seal.

## Files

- `CONFIG/BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_SEAL_V0.1.json`
- `src/crt_radar/btc_season_semantic_mapping_approval.py`
- `tests/test_btc_season_semantic_mapping_approval.py`

No existing candidate, runtime, governance, weight, threshold, mNAV or
Production file is modified by this seal.

## Verification

- Approval-seal targeted tests: `9 / 9 PASS`
- Full radar regression: `336 / 336 PASS`
- Runtime import of the approval validator: absent
- Season output: `BLOCKED / null`

This approval is necessary evidence for a possible later runtime-promotion
review. It is not runtime-promotion approval and does not authorize the next
engineering gate by itself.
