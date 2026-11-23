# Public archived evidence → two-company health replay

This is offline composition of existing CRT interfaces, not another health model,
collector, valuation formula, source authority, daily duty entry or scheduler.
It prepares a shared evidence input for later PRE/POST work; it does not make
cloud tasks share local storage or execute investment reasoning.

```text
python -m crt_radar.company_health_evidence_replay --issuer-archive <existing-public-archive> --source-gate <saved-gate.json> --output-dir <new-isolated-directory> --main-sha <verified-current-main-sha>
```

The source archive uses `build_archived_issuer_ct_inputs()`'s existing
`sec-disclosures/manifest.json`, original SEC bytes, and optional original
`shares-raw/` / `ledger-raw/` receipts. The established reader validates CIK,
accession, document/parent relationships, raw hashes and visibility clocks.
Copying receipts preserves their actual original retrieval dates. It is not a
new acquisition, new official source or a revision of historical facts.

The saved Source Gate run supplies the market cutoff; a blocked market gate
does not erase independent company facts. The replay binds its actual run ID,
idempotency key, registry hash, full gate hash and qualification to the generated
Evidence Pack. Pack/gate cutoff, authority and lineage mismatches are rejected.
Private capital/profile input is not accepted. No full daily runner is called.

For each of two new isolated ObservationStore files, the entry reuses:

`official archive reader → Treasury Company CT → build_evidence_pack() → build_common_equity_health()`

Both MSTR and ASST retain the original six dimensions, numeric levels, missing
claims, contradictions and provenance. Facts with conflicting asset/issuer
identities are excluded explicitly from the calculation view, never reassigned
to the other issuer; the original sealed pack is retained. The existing Strive
report coverage qualification is included as a separate research claim, not a
seventh dimension. Missing initial preferred evidence cannot be replaced by
dynamic claims or conditional issuance terms.
The actual qualified comparison window is explicit. When a newer reported
snapshot lacks qualified dilution/scope, the older comparison remains available
as historical research but the current-health claim is BLOCKED. It is never
silently relabeled as the latest company observation.

Receipts record main SHA, actual calculation-source file hashes, pack hash,
archive inventory hash, data cutoff and actual validation time. Validation time
is not source publication or first visibility. Replays can have different real
validation times while their health calculation hashes and pack hashes match.
Archive/gate fingerprints are rechecked after both calculations. No previous
output or store is overwritten. The output directory must not overlap source
inputs or the repository. The CLI only writes its explicit new isolated output.

The original CT metadata validator now also honors a source's explicit STALE,
INVALID or BLOCKED state and an explicitly supplied `valid_until_ms`. This fixes
a reproduced stale-source comparison leak. It does not invent a default filing
TTL, change dilution requirements or discard historical source archives.
Absent freshness proof is not a new assertion that an archived cash balance is
current or deployable.

MSTR Ledger reported dates are not ADSO effective dates. Dated research evidence
does not close missing dilution/disclosure requirements. ASST's warrant scope,
settlement, initial/dynamic preferred claims, net proceeds and causal deployment
keep their existing independent qualifications. Available historical facts do
not clear formal mNAV, residual value, allocation or BUY gates.

## PR #152 comparison

PR #152 remains unmerged. Its pure archive hash/identity checks, preservation of
original retrieval receipts and explicit output isolation are compatible ideas
reused here through current-main interfaces. Its collection loop, private-profile
load, broker-price path, live network calls, collection state and scheduler
assumptions are not imported or enabled. No old CT implementation is cherry-picked
over subsequent current-main fixes.

Receipt success proves deterministic local evidence/qualification reproduction,
not company safety, causal superiority, a fresh full market observation or Q5
reasoning. Production stays NOT_APPROVED, external actions NONE, capital decisions
USER_ONLY and machine execution FORBIDDEN. Runtime, duty tasks, queues, personal
portfolios and PRE/POST records are untouched.
