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

## 16 KiB scope

16 KiB equals 16,384 UTF-8 bytes, not 16 bits and not the
IBKR TWS market-data intake limit.

Existing CRT one-shot Smoke Test requests keep their versioned
16 KiB input ceiling and existing fail-closed behavior. Do not
silently increase, bypass, or remove that contract.

Raw source captures, local Evidence Packs, source histories,
Commander calculations, and full investment-decision evidence do
not inherit the Smoke Test's budget as an intrinsic data limit.

If decision-critical facts exceed the Smoke Test budget, block
that request without deleting facts. A new full-decision delivery
contract may be proposed only after a representative qualified
fixture demonstrates the real byte size, model input tokens,
provider/model limits, cost, latency, privacy, provenance,
receiver comprehension, and independent approval boundaries.

The new contract must be versioned and tested separately.
A hypothetical 32 KiB budget is not an accepted default.
Do not turn on provider delivery or production permissions
as a consequence of a successful offline test.

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

The 27,997-byte payload is deliberately NOT compatible with
the unchanged 16 KiB smoke request. Offline bridge decoding
is verified. End-to-end GPT semantic understanding and a
live qualified full-decision delivery contract remain unproven.

All figures above are offline fixture results, not live
qualified market acceptance or demonstrated investment alpha.

## Required regression protection

Tests must reproduce the previously observed nested-duplicate
failure patterns using a representative source fixture.

They must verify lossless reference expansion, non-merging of
conflicting observations, no uncontrolled repeated large
objects on the actual encoded wire, preserved authority and
privacy rules, and proper smoke-request rejection.

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
