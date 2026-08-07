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

Critical missing/stale/invalid/unverifiable data must fail closed. No zero-fill, silent stale reuse, or guessed values.

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

## Output Principle

Raw data may contain thousands of observations. The Evidence Pack should contain only the small subset that materially improves the five North Star answers.

Before adding an item ask:

> If this item disappeared, would GPT materially lose decision quality on season, weather, dominant forces, asset roles, capital strategy, or evidence trust?

If not, keep it outside the pack.

## Authority Boundary

The Evidence Pack is evidence only.

- It does not authorize trades.
- It does not modify formal models.
- It does not replace GPT judgment.
- It does not replace the user's final capital decision.
