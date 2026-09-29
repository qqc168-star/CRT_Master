# CRT Overbalance Replay Challenger V0.1 — research note

Base main: `d1f2f8b559f10eca4dcc2033383872965b169219`.
Branch: `codex/overbalance-replay-challenger-v01`, in a new isolated worktree.

## Measurement and replay use

The existing `btc_transition_replay_evidence.py` now supports an optional
`price_time_overbalance_measurement` in its replay snapshot. No runtime consumer
or formal sequence is wired to it. Existing structure and 50WMA outputs are
unchanged; measurement readiness does not change their classifications or state.
The existing OHLC validator is reused. There is no pivot/swing detector.

Construct one immutable `FrozenRallyReference` with the six supplied reference
fields (`reference_start_at`, `reference_end_at`, `reference_start_price`,
`reference_high_price`, `reference_frozen_at`, `reference_provenance`) and
`candidate_start_at` / `candidate_start_price`. Timestamps in the reference use
timezone-qualified ISO strings. Reuse that same object for the candidate's entire
replay. Dates must satisfy start ≤ end ≤ freeze ≤ candidate start ≤ as-of.

Call `build_price_time_overbalance_measurement(daily_bars, reference=reference,
as_of=as_of, previous_measurement=earlier_result)` directly, or supply
`overbalance_daily_bars`, `overbalance_reference`, and optional
`previous_overbalance_measurement` to `build_transition_replay_snapshot`.
Without the optional arguments the snapshot retains its original shape.

Daily rows contain OHLC, `day_closed_at`, `available_at`, and an explicit boolean
`is_complete`. Only complete, visible daily bars are used. Daily close must not
postdate availability. Incomplete and not-yet-visible bars cannot change past
results. Unknown completion, duplicate timestamps, unsorted bars, missing daily
intervals and unsupported reference highs block the measurement. Reference bars
must already be available at freeze; later observations cannot reconstruct it.

The common counting convention is completed 24-hour intervals **(start, first
highest-high occurrence]**. Start is an anchor boundary, excluded from the count;
the first following completed bar has duration one. Reference end must be a
covered daily close; reference duration stops at the first reference maximum,
even if reference end is later. Candidate duration likewise stops at its running
maximum's first occurrence. Equal highs retain the earlier occurrence. Declining
prices and elapsed days alone cannot strengthen time overbalance. Reference
duration must be positive; no calendar-duration substitution fills missing bars.

Both gains are `(high / starting price - 1) * 100`. Price ratio divides candidate
gain by reference gain; time ratio divides their bar durations. Reference gain
must be positive. Crossings use strict `> 1`, never `>= 1`. Decimal price ratios
are compared with exact rational arithmetic to avoid floating-point equality
creating false crossings; numeric outputs remain finite ordinary numbers.
First crossing timestamps name the completed daily bar; its separate availability
clock is retained in the local observations, so late disclosure is not backdated
as knowledge available at bar close.

## Freeze, provenance and failure

The reference object is frozen, and output fingerprints bind its anchors,
provenance and frozen supporting bars. Supplying the previous measurement checks
its integrity and rejects a changed reference or previously visible candidate
history. Retain the first frozen object/checkpoint when continuing a replay.
A stateless function cannot authenticate a deliberately backdated source or
discover an earlier invocation that was not supplied. Hashes are mutation checks,
not signatures; original source vintages and freeze attribution remain required.

Historical envelope exceedance is never erased by a later price collapse. The
snapshot separately projects the **existing** structure measurement's
`candidate_invalidation_anchor_raw_breach_at`, only for the same candidate start.
Its raw-breach wording remains intact: this is not newly confirmed invalidation,
a new lower-low threshold, fixed stop, control zone or expiry rule.

The sole positive interpretation is
`EARLY_TRANSITION_PRESSURE_AVAILABLE_FOR_ANALYST`. It does not confirm a bull
market, Spring, control transfer, capital eligibility or durable price recovery.

## Red-team acceptance intent

Tests contain minimal **synthetic research fixtures**, not newly acquired or
independently verified historical OHLC. Calendar labels describe failure archetypes
and never select production rules:

- **2023 early-transition intent:** a both-exceeded measurement can precede a
  complete closure from the existing classified research evaluator. The fixture
  supplies incomplete and later complete classifications; measurement never
  assigns them. This demonstrates compatibility, not empirical historical timing.
- **March 2022 failed-candidate intent:** both-exceeded remains historically true
  when the existing structural raw-breach measurement subsequently appears.
- **2022 momentum-trap intent:** price-only exceedance followed by decline never
  becomes BOTH merely because more days pass.

These examples prevent overclaiming. They do not establish universal lead time,
incremental trading performance, historical Challenger replication or durability.
No collector was added to fill missing source data. The optional 2021 case is not
claimed. No new 50WMA, 50% reclaim comparator, score, gate, vote or engine exists.

## Authority and boundary

Model, weight, threshold, season-transition and external-action authorities remain
NONE; action output remains NONE; no external action is performed. Machines may
neither determine BTC season nor confirm a bull transition. Capital decisions
remain USER_ONLY, execution FORBIDDEN, production NOT_APPROVED.

The change is restricted to the existing replay module, its tests and this note.
Formal Season/Input Binding, research evaluator sequence, Warning Overlay,
Evidence Pack, GPT bridge, Commander, Capital Posture, IBKR, transport and
STRC/SATA doctrine are unchanged. Bridge impact is zero bytes; the existing full
fixture remains 16,155 / 16,384 bytes, checked by the unchanged regression suite.
