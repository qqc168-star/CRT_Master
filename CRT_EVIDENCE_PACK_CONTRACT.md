# CRT Evidence Pack Contract

## Purpose

The Evidence Pack is the automation system's final product for GPT analysis. It is not a trading signal, dashboard, data dump, or news digest.

Its job is to transform large amounts of raw market information into a small, reproducible, high-density evidence set that lets GPT spend its effort on judgment rather than data preparation.

## Automation Pipeline

`Collect -> Validate -> Normalize -> Calculate -> Compare -> Detect -> Distill -> Evidence Pack`

## Required Sections

### 1. Data Health

For every decision-relevant source or family:

- source identity;
- observation timestamp;
- freshness state;
- schema / numeric validation state;
- critical vs noncritical status;
- missing state;
- fallback state when formally allowed;
- explicit BLOCKED reason when critical evidence is unusable.

Critical missing/stale/invalid/unverifiable evidence must fail closed at the smallest affected claim, metric, or calculation scope. It must not cascade `BLOCKED` into independent valid evidence.

When the strongest intended claim is unsupported, first reduce the claim to the strongest narrower statement actually supported by the evidence. For example, an unusable total-market field may block a total-market claim while verified constituent or tracked-basket trends remain usable.

No zero-fill, silent stale reuse, guessed values, guessed identities, or fabricated timestamp precision is allowed.

### Evidence Precision and Use

Evidence precision must be proportional to its use.

- Directional / research evidence may support trend, direction, breadth, acceleration, and structural context with explicitly partial or tracked-basket coverage.
- Deterministic / comparable evidence requires stable semantics and comparable scope across observations, but does not require complete-universe coverage when the claim is explicitly limited to the tracked scope.
- Formal / action-critical evidence requires the completeness and precision necessary for the exact formal claim.

`PARTIAL` means limited scope, not unusable evidence. `BLOCKED` must identify the affected claim or calculation rather than erase neighboring valid facts.

Automation should preserve real lower-precision evidence and label its limitations; GPT decides how much weight it deserves in qualitative judgment.

### 2. Six-Layer Market Evidence

The pack should carry only evidence required by the approved CRT framework for:

- L1 Macro
- L2 USD / Rates
- L3 Credit / Liquidity
- L4 Leverage
- L5 On-chain Value
- L6 Price Structure

Approved deterministic formulas may be calculated by automation. A score remains evidence and must not automatically become a BTC-season conclusion.

### 3. Change

Where decision-relevant, expose:

- 1D change
- 7D change
- 30D change

Prefer direction and acceleration information that helps identify marginal improvement, deterioration, stabilization, or reversal candidates.

### 4. Significant Changes and Extremes

Surface only materially important changes or approved threshold / historical-extreme conditions.

### 5. Divergences and Conflicts

Highlight cross-signal relationships that deserve analyst attention, such as leverage repair without price confirmation or on-chain value improvement against macro deterioration.

Automation may flag the relationship; GPT owns the causal interpretation.

### 6. Dominant Change List

Produce a short list of the day's highest-value changes. Default target: no more than 5-8 items unless exceptional conditions justify more.

If everything is highlighted, nothing is distilled.

### 7. Asset Facts

For each formally tracked asset, include only facts that can change role or capital analysis.

Examples include price, yield/distribution, dilution/share count, BTC holdings per share, mNAV where formally defined, company financing or repurchase events, and other approved asset-specific facts.

Automation must not convert these facts directly into an autonomous BUY or SELL instruction.

### 8. Decision-Relevant Events

Include only events that can plausibly affect a CRT layer, asset role, invalidation, or execution risk. Repeated generic news should not enter the pack.

### 9. Blockers

Explicitly list unresolved data or formal-model gaps that prevent a confident CRT judgment.

### Reflexivity Overlay Mapping (additive V0.2 contract)

`CRT-ISSUER-001` is a `NON_WEIGHTED_EVIDENCE_OVERLAY`. It reuses the existing generic V0.2 sections and does not add a new top-level section:

- verified issuer facts, approved market-reaction facts, and approved deterministic calculation results enter `asset_facts.items`;
- issuer actions with separate execution and disclosure windows enter `decision_relevant_events.items`;
- unresolved identity, source, supersession, window, share-basis, calculation, or coverage conditions enter `blockers.items`.

Every overlay-backed section must expose `section_state`, `coverage_state` where applicable, `overlay_id`, `overlay_type`, and `items`. Missing input, `null`, or a missing `items` field is unknown and must fail closed. An empty `items` list is verified empty only when coverage is `COMPLETE` and `empty_reason` is `VERIFIED_NO_MATCH`; otherwise the section remains `BLOCKED` or incomplete.

Execution, disclosure, and reaction windows are distinct semantic clocks and must not be substituted for one another. Superseded events remain traceable but are excluded from active calculations. Market-response facts and market-dependent calculations remain `BLOCKED` until both their data-source lock and observation-window specification are formally approved in current `main`.

The overlay may calculate only formula-locked metrics from explicit, source-referenced inputs. A deterministic result is evidence, not a causal claim. The overlay must not emit `reflexivity_score`, an automatic asset role, `capital_strategy`, BUY, or SELL.

## Output Principle

Raw data may contain thousands of observations. The Evidence Pack should contain only the small subset that materially improves the five North Star answers.

Before adding an item ask:

> If this item disappeared, would GPT materially lose decision quality on season, weather, dominant forces, asset roles, capital strategy, or evidence trust?

If not, keep it outside the pack.

## Authority Boundary

The Evidence Pack is evidence only.

- Its top-level `action_output` is always `"NONE"`.
- It does not authorize trades.
- It does not modify formal models.
- It does not replace GPT judgment.
- It does not replace the user's final capital decision.
