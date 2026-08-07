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

## Lean Rule

Before adding a file, module, metric, process, or automation, ask:

> If this disappeared, would CRT materially lose its ability to judge season, weather, dominant forces, asset roles, capital actions, or the trustworthiness of evidence supporting them?

If not, default to not adding it.
