# CRT Core Contract

## North Star

CRT exists to improve capital decisions by answering five questions:

1. What BTC season are we in?
2. Is market weather improving or worsening?
3. What forces are dominant?
4. What role should each tracked asset play in the current regime?
5. Should capital BUY, SELL, HOLD, WAIT, or ROTATE?

Everything in CRT must serve at least one of these questions or protect the integrity of the answers.

## Role Boundary

### Automation — Evidence Kitchen / Sous-chef

Automation performs deterministic, repeatable work:

- collect decision-relevant data;
- validate source, schema, timestamp, freshness, and numeric sanity;
- normalize and calculate approved metrics;
- compare material 1D / 7D / 30D changes;
- detect meaningful changes, extremes, divergences, and conflicts;
- compress results into a CRT Evidence Pack;
- fail closed when critical evidence is missing, stale, invalid, or unverifiable.

Automation must not invent investment logic, silently alter approved formal models, infer open-ended causal narratives, assign final asset roles, issue autonomous trade decisions, or perform external actions.

### GPT — Chief Analyst / Chef

GPT performs high-level judgment:

- causal reasoning and multi-evidence synthesis;
- distinguish independent evidence from correlated signals;
- interpret leading, coincident, and lagging evidence;
- judge BTC season, market weather, and dominant forces;
- determine asset roles under the current regime;
- propose capital strategy with evidence, uncertainty, invalidation, and what would change the view.

GPT should not repeatedly perform large deterministic calculations that belong in automation and must not silently modify approved formal models, weights, thresholds, or governance locks.

### User — Capital Decision Authority

The user defines objectives and risk constraints, approves formal model changes, makes final BUY / SELL / HOLD / WAIT / ROTATE decisions, and alone authorizes real-world execution outside CRT.

## Core Workflow

`World -> Automation -> CRT Evidence Pack -> GPT Analysis -> User Decision`

Automation prepares evidence. GPT creates judgment. Human commits capital.

## Fail-Closed Rule

Missing, stale, invalid, or unverifiable critical evidence must produce `BLOCKED` rather than a fabricated value or false certainty.

Evidence is not a decision. A score is not a season by itself. A historical PASS does not make future evidence valid.

## Evidence Precision Constitution

Precision follows the claim and decision use; the claim must not be forced to match the maximum precision available from a source.

CRT uses three evidence precision levels:

### Directional / Research Evidence

Use for trend, direction, acceleration, breadth, structural context, and hypothesis formation.

Directional evidence may use partial but real coverage, a stable tracked basket, mature processed research sources, and date- or period-level timestamps when those are sufficient for the claim.

It does not require complete-universe coverage, a formal total, or millisecond timestamp precision unless the claim itself depends on them.

### Deterministic / Comparable Evidence

Use for reproducible 1D / 7D / 30D comparisons and other deterministic change calculations.

It requires stable metric semantics, comparable scope or basket, sufficient identity, explicit as-of semantics, and reproducible calculation inputs.

Partial universe coverage is acceptable when the comparison scope is explicit and materially comparable across observations.

### Formal / Action-Critical Evidence

Use for exact total-market claims, formal model inputs, approved thresholds, gates, market-dependent formula locks, Production promotion, or external actions.

These claims require the coverage, identity, timing precision, prerequisites, and approvals necessary for that exact claim.

### Claim-Scoped Fail-Closed Rule

`BLOCKED` is claim-scoped, metric-scoped, or calculation-scoped. It must not automatically invalidate independent evidence that remains real, relevant, and usable for a narrower claim.

A missing or invalid total does not invalidate verified constituents. Incomplete universe coverage does not invalidate a clearly labeled tracked-basket trend. Date-level source timing does not require invention of a false millisecond timestamp.

When evidence cannot support the strongest intended claim, CRT must first reduce claim scope or precision and preserve the valid evidence. It should discard the evidence only when the remaining evidence cannot support a decision-relevant claim at any appropriate precision level.

Partial real evidence must remain visible with explicit scope, provenance, as-of semantics, and limitations.

Fail-closed still forbids fabricated values, zero-fill, guessed identities, silent stale reuse, fake timestamps, or promotion of lower-precision evidence into a stronger claim than it supports.

GPT may use appropriately labeled lower-precision evidence for qualitative judgment, but must state uncertainty and must not silently promote it into a formal exact claim.

## Governance Boundary

- Production remains `NOT_APPROVED` unless explicitly changed by later formal approval.
- External Action Authority remains `NONE` unless explicitly changed by later formal approval.
- No trading, account access, or fund movement is authorized by this contract.
- Existing approved formal models, weights, thresholds, mNAV semantics, and other formal locks are not changed by this contract.
- Existing stash state must not be applied, popped, dropped, or rewritten by this contract.

## Knowledge Survival Rule

No essential CRT knowledge may depend on one chat session.

`Conversation -> Finding -> Verification -> User Approval -> Contract / Code / Test -> Git commit`

Unapproved discussion may disappear. Approved knowledge that must survive context loss must be promoted into the repository.

## Finding Retention Filter

Every newly discovered viewpoint, indicator, rule, module, or proposed permanent CRT knowledge item must be re-examined through all three questions before promotion:

1. **Necessity** - If this finding disappeared, would CRT materially lose decision quality, evidence integrity, or the ability to answer a North Star question?
2. **Purpose** - What exact CRT decision, evidence task, or governance problem does the finding serve?
3. **Specificity** - Does the finding address a demonstrated CRT gap directly, rather than duplicate an existing capability or expand scope without a concrete need?

Failure on any one question means the finding must not be promoted into permanent CRT structure. It may remain as Research / Observation when it still has evidentiary value, or be discarded when it does not.

Passing all three questions grants only eligibility for verification. It does not automatically create a formal metric, score, threshold, layer, model, production rule, or trading authority.

## Lean Rule

Before adding a file, module, metric, process, or automation, ask:

> If this disappeared, would CRT materially lose its ability to judge season, weather, dominant forces, asset roles, capital actions, or the trustworthiness of evidence supporting them?

If not, default to not adding it.
