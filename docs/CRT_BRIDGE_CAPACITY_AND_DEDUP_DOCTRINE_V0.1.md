# CRT Bridge Capacity and Dedup Doctrine V0.1

## Purpose and decision linkage

Evidence completeness and investment decision quality take priority
over byte-count optimization. Preserve original evidence and all
decision-relevant observations, contradictions, blockers, provenance,
quality states, timestamps, asset identities, and formal semantics.

The actual goal is a complete CRT decision chain, not a small JSON file.

## Verified failure patterns

1. Horizontal copying: five analysis inputs deepcopy the same
   four-asset market snapshot.
2. Vertical nesting: the Commander Battle Map embeds the full
   upstream live-market handoff.
3. Repackaging: the Battle Map repeats machine evidence while
   the Evidence Pack carries both the handoff and Battle Map.
4. Source fanout: nine parsed source families appear in seventeen
   section uses. Only exact-equal family payloads may share refs.
5. Historical overlap: current/previous observations can already
   occur in historical rows. This is a candidate, not proof of
   waste: historical identity and claim semantics must be checked.
6. Budget inversion: an internal 16 KiB smoke-test budget
   was treated as if it were a permanent full-decision constraint.

The 17-copy market incident counts serialized occurrences,
not independent market observations.

## Prevention at the source of duplication

Before making new nested evidence surfaces, identify the canonical
owner and the downstream consumer. Prefer explicit, scoped references
over repeated complete parent objects in transport projections.

The sealed Evidence Pack may legitimately retain independent
auditable surfaces. Do not break an existing pack validator, source
hash, or evidence lineage merely to reduce serialization size.

Cross-layer comparison covers source, Evidence Pack, analysis input,
Commander Battle Map, GPT bridge, and receiver interpretation.

Only coalesce objects when the observation identity AND literal
content are equivalent. Identity includes asset, metric, source,
source hash, observation/retrieval/effective clock, quality state,
unit, schema, semantic basis, and applicable scope.

Never merge different asset identities, clocks, interpretations,
source authority, opposite claims, missing inputs, or blockers.
Matching values alone are not a shared identity.

Every encoded reference must be reversible, deterministic, collision
checked, privacy checked, and recognizable at the receiving boundary.
A Python roundtrip does not establish that GPT interpreted the
original meaning correctly.

## Current capacity approval (2026-11-12)

16 KiB equals 16,384 UTF-8 bytes, not 16 bits and not the
IBKR TWS market-data intake limit.

The user explicitly removed the CRT total-input limit for PR #171.
New Bridge and Responses V0.2 requests have no 16 KiB (or replacement
total byte) ceiling. Historical V0.1 receipts keep their original hash,
instructions and declared guardrails; they are not rewritten or resent.

Raw source captures, local Evidence Packs, source histories,
Commander calculations, and full investment-decision evidence do
not inherit the Smoke Test's budget as an intrinsic data limit.

Size never authorizes omission of valid observations, history, blockers,
company health, mNAV evidence or locks. Privacy allowlisting and existing
financial/source qualification still apply. Exact content AND inherited
source/asset/metric/clock/version/quality identity select reversible SHA256
references; matching numeric values are not identity. No new financial model.

The existing worker routes large input through the official Uploads API:
numbered parts, local SHA256/length validation, durable acknowledgements,
ordered completion with the provider MD5 check, and a downloaded whole-file
SHA256 check before a single Responses inference uses the completed text file.
The 64 KiB inline routing threshold and 63 KiB part data size are operational
batch sizes, not total input limits. Explicit HTTP 413 reduces part size or
routes inline data to parts. Input-byte retries are bounded to three attempts
per operation; interruption retains INPUT_TRANSFER_PENDING and resumes missing
parts. A lost completion acknowledgement is reconciled only by verified file
content, never its name. Unknown inference outcomes keep the existing
RECONCILIATION_REQUIRED lock and are never automatically sent again.

Original source files and prior immutable receipts remain untouched. Within
the Bridge each exact evidence object has one canonical content entry; local
transfer parts use a content-addressed store. Distinct positions in a byte
stream remain ordered positions, not invented distinct market evidence.

The provider still has physical file/context limits. A provider rejection
retains the entire job and evidence as pending; it cannot be called success or
be repaired by dropping evidence. No finite model context is represented as
unlimited. Input tokens, cost and receiver comprehension are NOT_MEASURED /
NOT_YET_PROVEN without an approved live test. No provider, notification or
production permission is enabled by this approval.

Official API schemas: [Uploads](https://developers.openai.com/api/reference/resources/uploads/methods/create),
[parts](https://developers.openai.com/api/reference/resources/uploads/subresources/parts/methods/create),
[completion](https://developers.openai.com/api/reference/resources/uploads/methods/complete),
[file inputs](https://developers.openai.com/api/docs/guides/file-inputs).

## Required comparisons

Use the SAME source facts and as-of clock for every comparison.
Report separately:

- raw canonical Evidence Pack bytes;
- wire-encoded bridge bytes;
- restored semantic-view bytes;
- actual model input tokens when measured by an appropriate
  tokenizer or provider usage, otherwise NOT_MEASURED;
- source-identity and critical-information parity;
- unexpected exact or semantic duplication;
- request accepted/rejected under its actual versioned contract.

Never sum nested duplicate byte counts as if independent.
Never confuse test-expected rejection with successful delivery.
Never equate offline expansion with a real model judgment.

## Known offline measurements and limitations

The synthetic four-asset Commander example measured 98,999
bytes before deduplication, 18,815 bytes after snapshot sharing,
and 18,103 bytes after source-family sharing.

The separate full synthetic bridge example measured 28,271
bytes before source-family sharing and 27,997 bytes after it.
Its no-premarket baseline measured 15,251 bytes.

After both fixes, that actual encoded wire example had zero
equal nested object repeats at or above 256 bytes. This does
NOT prove absence of smaller, overlapping, or semantic
duplicates in every live or future evidence combination.

The 27,997-byte payload was incompatible with the then-current V0.1
16 KiB request. That historical rejection no longer defines new V0.2
input acceptance. End-to-end GPT semantic understanding remains unproven.

All figures above are offline fixture results, not live
qualified market acceptance or demonstrated investment alpha.

## Required regression protection

Tests must reproduce the previously observed nested-duplicate
failure patterns using a representative source fixture.

They must verify lossless reference expansion, non-merging of
conflicting observations, no uncontrolled repeated large
objects on the actual encoded wire, preserved authority and
privacy rules, and acceptance above the former Smoke byte limit.

A future source-structure change must compare the full
decision-relevant semantic view, not only count PASS tests.
If model-side interpretation is not tested, label it BLOCKED
or NOT_YET_PROVEN, never PASS.

## Unchanged formal boundaries

Six-layer weights, signal thresholds, mNAV semantics, Season
authority, Production NOT_APPROVED, External Action Authority
NONE, and USER_ONLY capital authority are unchanged.

No trading, account action, real provider call, or automatic
transport enabling is authorized by this doctrine.
