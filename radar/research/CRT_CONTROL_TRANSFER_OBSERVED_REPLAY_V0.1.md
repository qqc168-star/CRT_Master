# Control-transfer observed replay interface V0.1

Research implementation supplement; no formal model/source/season authority.
The sealed `CRT_CONTROL_TRANSFER_VALIDATION_CONTRACT_V0.1.md` and its
2015/2020/2022/2023 classification fixtures remain unchanged.

## Existing chain

`l6_public_capture.archive_structure_observation()` reuses the original GO4
archive reader (now shared in `source_gate_runner`) and existing 201-day parser.
It performs no fetch. Original bytes, registered source/request, SHA256, length,
first successful retrieval and research-only authority must verify. Re-evaluation
rechecks raw bytes and reconstructs the selected observation from that reader.
Stored local hashes prove content integrity; they do not grant formal authority.

Market window timestamps describe completed UTC daily bars. `available_at` is
the actual first capture time, shared by historical bars downloaded together.
CRT `recorded_at_ms` is the new ingestion time; `formed_at_ms` is candidate
analysis time, never a historical price-crossing timestamp. Older backfilled bars
cannot be visible before capture/recording, nor become historical forecasts.
`source_available_at_ms` is the first proven availability bound (successful
retrieval), not an invented issuer publication time. Independent source
publication time is unknown (`source_published_at_ms = null`). The archive's
availability proof, market time and CRT clocks remain separately attributable.

The adapter stores observations in the existing ObservationStore database.
Identity is source, product, market window and event definition, independent of
file hash, download time and filename. Identical downloads retain the first
record. Changed content within the same window fails closed; it cannot replace
the original observation. Use an isolated database for research replay.

## Candidate and follow-up

`freeze_control_transfer_candidate()` is called only for an analyst-classified
candidate under the existing classification contract. It requires the archived
observation ID, formation clock, `classification_provenance` and the existing
`build_structure_measurements()` reference arguments. `reference_provenance`
must identify an archived reference observation visible when the references
were frozen. No numeric references or meaningful-breakout classification are
invented by the adapter. Frozen reference locks and candidate snapshots reject
rewrites. Repeating the same candidate preserves its original formation time.

Observed inputs use schema `CRT_BTC_CONTROL_TRANSFER_OBSERVED_EVIDENCE_V0.1`,
the existing NONE authority envelope and `candidate_event_id`. A `post_c_test`
supplies `observation_id`, `frozen_reference_hash` and the existing classification
fields: `old_control_zone_result`, `candidate_structure_result`,
`renewed_expansion`, `new_local_control_high_break`. Caller `event_id`,
`event_order` and `distinct_event` do not establish chronology or independence.

The follow-up window must be after both the original market window and actual
candidate formation. Raw bytes and observations must already be visible at
evaluation. Overlapping windows, renamed observations and mismatched references
are blocked. Same-exchange later observations prove temporal persistence, not
independent causal sources (`causal_source_independence = NOT_PROVEN`).
Existing research classifications still determine support, rejection or pending;
machine chronology/integrity checks do not prove analyst classification quality.
A reversal review additionally requires a previously stored validated assessment
and an observation after its actual validation time, not just after market time.

Without a candidate, `observation_id` alone preserves qualified source facts in
the Evidence Pack, with INCONCLUSIVE and explicit missing frozen-reference /
analyst-candidate reasons. Missing follow-up leaves VALIDATION_PENDING. No
historic classification fixture alone can become observed Evidence Pack proof.

## Immutable history and isolation

Candidates, assessments, warning starts/withdrawals and warning snapshots use
an append-only research table in the existing observation database. Stable
identities deduplicate replay and restart. Existing judgments are never updated;
new outcomes append records. The first validation clock is retained on replay.
Warning onset and episode history survive withdrawal, so a final NO_TRANSITION
still counts a previously issued warning as a false positive.

`build_evidence_pack()` uses its existing control-transfer evidence interface.
It restores warning history from the same observation database when no previous
overlay is supplied. Local archive-root paths are omitted from projected results.
Original GO4 archives, existing Runtime and schedules are not modified.

Formal season remains null. Missing formal evidence retains SCENARIO_0; Binance
research observations cannot replace locked three-exchange L6 evidence.
Production NOT_APPROVED, External Action Authority NONE, capital authority
USER_ONLY, six-layer weights and thresholds are unchanged. No network/model,
broker, notification, trading or Q2 action is part of this replay interface.
