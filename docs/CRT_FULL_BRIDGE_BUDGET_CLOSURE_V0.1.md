# CRT Full Bridge Budget Closure V0.1

Base: `da6146a1f487654870c50c00cd155d26e67a8e05`.

This delta concerns the existing minimized GPT bridge only. It does not change
source collectors, Company Health, valuation, CT clocks, capital holdings,
Commander, six-layer weights, light thresholds, Formal Season, Production
approval or External Action Authority. No trading action is introduced.

## Byte attribution before construction

The retained First Real Capital Decision Run produced a **58,803-byte** bridge
before detail compaction. The existing full-context projection was **16,616
bytes**, exceeding the unchanged ceiling. These are canonical UTF-8 JSON sizes
using `ensure_ascii=False`, `sort_keys=True` and `separators=(",", ":")`.

The five largest raw contributors were:

| Named section | Bytes |
| --- | ---: |
| `market_context.changes` | 21,821 |
| `market_context.layers` | 8,930 |
| `market_context.season_transition_warning_overlay` | 8,144 |
| `analysis_contract` | 3,014 |
| `market_context.btc_bull_validation` | 2,874 |

Each number measures the standalone named section, including its key and object
wrapper. Nested sections overlap their parent; wrappers and commas prevent
direct summation. The raw payload and attribution report remain outside the
repository in the runtime audit archive.

The complete raw top-level attribution was: `market_context` 51,239,
`analysis_contract` 3,014, `issuer_ratio_observation` 1,734, `capital_state`
1,181, `event` 763, `privacy` 330, `authority` 294, payload hash 90, privacy
contract version 71, schema version 54 and state 43 bytes. Within capital,
active plans/tranches contributed 657 bytes. Other raw market contributors were
Treasury 2,088, distillation 1,988, model status 1,780, DVOL 1,492, ETF 939,
entry gate 430, transition diagnostic 347 and data health 343 bytes. No
`asset_strategy_delta` or portfolio-allocation section existed in this capture.

## Field classification

**A — DECISION_CRITICAL:** preserve actual values, machine-readable states,
clocks and blockers. This includes generated/as-of times and source evidence
binding; BTC current price, Season/Weather, entry/bull states, ETF 1D/7D/30D and
breadth, relevant leverage/liquidity/DVOL and contradictions; supplied qualified
MSTR/ASST market facts, paired issuer ratios and their change; Company Health
and formal mNAV states and decisive blockers; capital asset/quantity, supplied
cost basis, cash/reserve, active plans, tranche budgets, roles and stale flags.
The GPT analyst/user-decision boundary, required behavior, formal locks, top-level
authority and privacy remain explicit. MSTR retains
`REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME`, `NOT_CT_BOUND`,
`ADSO_EFFECTIVE_TIME_UNRESOLVED` and `OBSERVATION_ONLY`; ASST retains its separate
SEC effective clocks. Unknown values are never converted into zero or approval.

**B — DECISION_CONTEXT:** deterministic, reversible projection may remove
repeated structure without changing meaning. Permitted forms include exact-equal
`same_as` references, explicit inherited authority fields, reversible key-name or
glossary mappings and column/metric metadata encodings. Actual values remain
literal; readers must expand declared mappings and references before interpreting
fields. Different authority values cannot inherit a common value. Dictionary
insertion order must not select a different reference, schema index or hash.

**C — AUDIT_ONLY:** full provenance, non-trigger histories/baselines/rankings,
repeated explanations and nondecisive displays can stay in the Evidence Pack.
The bridge retains source/section hashes and explicit declarations:
`FULL_PROVENANCE_IN_EVIDENCE_PACK` and
`OMITTED_FROM_BRIDGE_NOT_ABSENT_FROM_EVIDENCE`.
Omission must not remove a missing, stale, partial, blocked, null or trigger
observation, a decisive blocker, or a critical current fact.

The current known scoring-support allowlist contains exactly these 13 metric
names:

```text
core_inflation_acceleration
real_policy_rate
unemployment_deterioration
market_cap_usd
mvrv
nupl
realized_cap_30d_log_change
realized_cap_usd
close_minus_sma200_over_atr20
return_20d_over_atr_vol
sma50_minus_sma200_over_atr20
mark_price
open_interest_contracts
```

A row in that allowlist is eligible for audit-only omission only when it is
non-trigger, `quality_state == VALID_FRESH`, and its value is not null. Unknown
metric names are not eligible. Current BTC price, OI notional, funding, USD/rates
liquidity and retained volume/CVD evidence remain decision context. Underlying
source/input-qualification blockers remain visible; omission does not grant
formal qualification to a proxy.

## Exact bridge projection

Compaction runs only when the payload plus its final hash exceeds the operational
target. Audit-only change histories become a section hash and omission declaration;
non-trigger scoring displays, duplicate explanatory labels and explicitly listed
Treasury baseline/CDF/benchmark columns remain bound to the full source market hash.
Bull category lists, blocked check reasons and decisive check values remain visible.
DVOL current values and trigger observations retain their clocks and change fields.

If further compaction is needed, six-layer observations share deterministic
`[as_of_ms, quality_state]` metadata; values remain literal. The Season research
overlay preserves states, authority, lights, veto, contradiction evidence and formal
locks. Equal Treasury asset fields and equal tranche budget/status/conditions are
stored once with explicit inheritance. Different JSON values, including `false`
versus `0` and integer versus float literals, cannot share a reference.

Equal child authority fields use a bit mask over sorted top-level authority keys;
only the specified original fields inherit. Additional repeated lock pairs use
an explicit `[field, literal_value]` table. The final deterministic key glossary
encodes field names only, leaving all values unchanged; tokens are absent from
original keys, collisions fail closed, and canonical roundtrip validation precedes
use. `expand_bridge_field_names` restores keys, authority references and tranches.
Metric metadata and Treasury inheritance have their own inline decoding rules.
Root fields, event, authority and privacy stay directly readable. Privacy checks
also run after expansion. There is no binary encoding or second transport path.

## Replay and source scope

The real capture includes BTC context, TFTC flow/breadth, MSTR Ledger and ASST SEC
issuer evidence, Treasury BLOCKED context, Season/Bull/Entry states and the GPT
handoff. It does **not** contain qualified MSTR/ASST IBKR market sections. Those
facts were retained separately in the qualified-equity intake artifact. This
replay must not claim that absent market sections survived compaction; optional
qualified facts are preserved and tested when supplied as inputs.

The original accepted private profile provides an old `as_of`, not an explicit
freshness assessment. Replay stale flags are supplied from the previous capital
assessment, not inferred as new live holdings or used to repair capital state.
Offline regression uses captured sanitized public context plus synthetic private
capital. Synthetic capital is never presented as live evidence. Raw private
profiles, account identifiers, contact details, credentials and local filesystem
paths must not enter the bridge or public fixture.

## Budget and acceptance

There remains one transport payload and one existing bridge path. No gzip,
base64 wrapper or raised ceiling is permitted. Canonical size must be **strictly
less than 16,384 bytes**; decision-critical overflow fails closed. The operational
headroom target is **at most 15,360 bytes**, not a new CRT formal semantic lock.

Acceptance requires the realistic full context to reach
`GPT_HANDOFF_READY` -> `BRIDGE_PAYLOAD_READY_LOCAL_ONLY` -> local enqueue and
validation. Repeated identical inputs and recursively reordered dictionaries
must produce identical payloads, byte counts and `bridge_payload_hash` values.
Supporting-context inflation must compact deterministically; oversized critical
input must fail closed even without a Treasury section.

The existing Season/Three-Army end-to-end fixture includes a full duplicated
Commander map. Base main returned local READY for its **112,985-byte** payload
without Treasury, although that input could not meet the transport ceiling.
The updated regression requires construction to reject it. A scoped test-only
capacity oracle retains the original source-fact, role and privacy assertions;
its oversized output is never treated as accepted or enqueued. Separate fitting
inputs prove optional qualified market/Commander facts survive unchanged.

Two historical Gold/Capital tests asserted an exact old 16,155-byte snapshot.
Their shared Company Health/portfolio fixture now measures 13,955 bytes while
retaining its hash, limitation and trade-off assertions. Their budget assertions
now enforce the 15 KiB operational target rather than the obsolete byte count.
No Gold, Capital Posture or Company Health implementation changed.

| Result | Status |
| --- | --- |
| Final canonical full-replay bytes / ceiling headroom | 15,334 / 1,050 bytes |
| Realistic full pipeline and outbox validation | PASS; duplicate enqueue skipped; offline request envelope validated |
| Payload/hash determinism | PASS, including recursively reversed dictionary order |
| Targeted tests / full regression | 89 targeted passed (87 bridge tests plus 2 corrected budget checks); 1,077 full regression passed |
| Compile / static / diff checks | PASS: compileall, program registry, read-only surface, git diff --check |

The retained original internal pack hash was verified before replay. The previous
real capital stale assessment was then supplied in memory and the replay pack was
rebound to its own hash. Final bridge hash:
`292e7d6b9b046bfc3ec96faf7e44dd1cf978b8c8d223ef4ef536f1e22934d41b`.
The replay performed no fresh retrieval or GPT network send. Validation is complete;
merge remains outside this dispatch's authorization.
