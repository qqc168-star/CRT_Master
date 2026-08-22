# CRT-BTC-001 V1.0 Source Intake Record V0.1

## Intake decision

- `SOURCE_ARTIFACT_FOUND = PASS`
- `SOURCE_INTEGRITY = PASS`
- `FORMAL_ACCEPTANCE_EVIDENCE = PASS`
- `RUNTIME_PROMOTION = BLOCKED`
- `SEASON_OUTPUT = null`
- `RESEARCH_DELTA_AUTHORITY = NONE`

This intake places the exact accepted `CRT_BTC_001_V1.0_FORMAL_ARCHIVE`
under Engineering SSOT. It is a source-recovery checkpoint, not a runtime
implementation or approval event.

## Engineering base

- Repository: `qqc168-star/CRT_Master`
- Verified `main` SHA at intake start:
  `feca2c73162d94ae4f0708a6e2d2327dd71f77b7`
- Intake date: `2026-08-21`
- Artifact path:
  `FORMAL_SOURCES/CRT-BTC-001_V1.0/CRT_BTC_001_V1.0_FORMAL_ARCHIVE.zip`

## Exact artifact identity

| Object | Size (bytes) | SHA-256 |
|---|---:|---|
| Formal archive | 300152 | `4556141b069596b24d78b8c4b5e19071f6b435f9748cd04891e91817e0a34c42` |
| Working body | 174760 | `5ba963b51bcf49839299c3ce4e7649728d3d8caa05d8ca442691689e667f0064` |
| Chapter 7 exact byte slice | 15262 | `fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26` |
| V1.0 release record | 950 | `1934a5f53bbd2b630f1f14f9205225755ab51831fd79e99a67f95b1a27ec1031` |
| User acceptance record | 409 | `9c8ae48d0802239a8ef8eb9130ed554fbfcf3481fecebc83946c2838c9e7744f` |

The internal package manifest declares:

- package `CRT_BTC_001_V1.0_FORMAL_ARCHIVE`;
- version `V1.0`;
- type `formal_archive`;
- scope `CH01-12`;
- status `FORMAL_ARCHIVE`;
- acceptance `AG-0_TO_AG-9_PASS`.

All 37 manifest-listed files and all 38 `SHA256SUMS.txt` entries are checked
byte-for-byte by the compatibility test. The V1.0 minimum test record contains
`TST-01` through `TST-15`, each recorded as `PASS`.

## Provenance boundary

This artifact does not claim recovery of the lost historical wording verbatim.
Its own source-evidence records distinguish the failed old-source search from
the evidence-based continuation that was drafted, reviewed, accepted at AG-9,
and released as V1.0 on 2026-07-21.

Recovery verification also found this exact V1.0 archive embedded in the
`CRT Master V1.9` lineage bundle (outer SHA-256
`6aacf07e7f8dba7dab8adf428d055f34a9f4953ecb3dc2ef0bf31a4c72c73bd0`).
The later V1.1-RC1 material states that CH01-CH07 are not modified, and its
Chapter 7 bytes match this V1.0 chapter. V1.1-RC1 does not supersede V1.0
because its AG-9 acceptance remains pending.

## Recovered Season State Transition Contract surface

Chapter 7 formally contains these state identifiers:

- `SE-WI`
- `SE-WI-SPC`
- `SE-SP`
- `SE-SP-SUC`
- `SE-SU`
- `SE-SU-AUC`
- `SE-AU`
- `SE-AU-WTC`
- `SE-X`

It also contains the five-step transition procedure:

1. keep the last valid season;
2. create a next-season candidate only when the required gates are complete;
3. wait for an independent later observation;
4. confirm only if the candidate persists and material counter-evidence clears;
5. invalidate a failed candidate or place a threatened confirmed season under
   review before a formally supported rollback.

The recovered Winter-to-Spring standard path requires Stage 3 or equivalent,
`C3`, `S2+`, and `E2+`, with no `D3`/`D4`, `CX`, `SX`, `VX`, or unresolved
high-quality `VETO`, and a classifiable value-supported or high-level-base
route. `E2` creates only `SE-WI-SPC`; it cannot confirm Spring. Confirmation
to `SE-SP` requires `E3`, continuing `C3`, `S3` with the required weekly and
spot support, an independent later validation, and no specified decisive
counter-evidence. Normal transitions are adjacent-only. Candidate failure
returns to the original season; a threatened confirmed season first uses
`SEASON_UNDER_REVIEW` and requires cross-confirmed damage before rollback.

## Compatibility and authority boundary

This intake deliberately does not translate the chapter prose into a new
machine-readable state machine. Such a translation requires a separately
reviewable semantic mapping and validator.

Until that gate is completed and approved:

- `season_router.status` remains
  `SPEC_NOT_RECOVERED_CANDIDATE_FAIL_CLOSED`;
- `score_may_determine_btc_season` remains `false`;
- runtime `season` remains `null`;
- `candidate_score` may supply only the candidate weather bucket;
- formal weights remain `20 / 20 / 17 / 25 / 13 / 5`;
- formal light thresholds remain `-60 / -35 / 35 / 60`;
- formal mNAV semantics remain `Diluted Equity mNAV`;
- BTC Bull Validation remains a `NON_WEIGHTED_EVIDENCE_OVERLAY` with formal
  model, weight, and threshold authority all `NONE`;
- Production remains `NOT_APPROVED`;
- External Action Authority remains `NONE` and action output remains `NONE`.

The separate Research Delta concerning 200D persistence/retest acceptance,
2019 and 2022 false-positive cases, competing Bull/Bear hypotheses, and
Apathetic/Euphoric Top remains research-only. It supplied no rule, state,
weight, threshold, confirmation, or inference in this intake.

## Next controlled gate

The next possible engineering change is a separate Season Contract Semantic
Mapping and Validator candidate. It must trace every machine rule to exact V1.0
Chapter 7 evidence, preserve candidate/confirmation hysteresis and rollback,
and remain fail-closed until its tests and approval are complete. This record
does not authorize that change.
