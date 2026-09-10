# CRT GOLDEN CROSS REATTACK RESEARCH DELTA 20260910

Status: `RESEARCH_ONLY_NOT_APPROVED`

Integration mode: `DOCUMENTATION_ONLY`

Engineering base: `39ffb1724229d7f37208bf9929d0b20899bc4e75`

## Purpose

This delta records how Golden Cross（黃金交叉）and post-event reattack（事件後再攻）research fits the existing CRT Control Transfer（控制權轉移）architecture.

It adds an analyst interpretation rule, not a new model, score, router, layer, vote, threshold, Formal Season（正式季節）transition, or trade action.

The decision question is:

> After a material price-structure event and its correction, does the first meaningful reattack（第一次有效再攻）take control with a Higher High（更高高點）, stall at a Lower High（更低高點）, or remain unresolved（未決）?

## Research source boundary

The research inputs are:

- `NoteGPT_Transcript_Bitcoin Golden Cross.docx`
- `NoteGPT_Transcript_Bitcoin This Sell Signal Is Freaking Out Investors (explained).docx`
- `CRT_RESEARCH_GOLDEN_CROSS_REATTACK_DELTA_V0.1.md`
- `SOURCE_EVIDENCE_NOTES.md`
- `READY_TO_IMPLEMENT_DELTA.md`
- `MANIFEST.json`

They are Research Input（研究輸入）only. Historical observations and live coordinates in those sources are not promoted to independently verified facts, Formal Model（正式模型）inputs, or permanent rules by this document.

## Consolidated research chain

Keep one chain:

`PRICE STRUCTURE EVENT`

`-> POST-EVENT PULLBACK`

`-> PULLBACK QUALITY`

`-> STRUCTURAL SURVIVAL`

`-> FIRST MEANINGFUL REATTACK`

`-> HIGHER HIGH / LOWER HIGH / UNRESOLVED`

`-> CONTROL TRANSFER INTERPRETATION`

The Golden Cross（黃金交叉）is an `EVENT ANCHOR / CONTEXT ONLY`（事件錨點／背景而已）. The event itself does not determine direction.

The structural discriminator（結構判別器）is the first meaningful reattack（第一次有效再攻）after the initial selloff or pullback.

## Current main fit assessment

Current `main`（目前主分支）already carries the required semantics through:

- `PRICE_ACCEPTANCE_AND_SMA200` for price acceptance（價格接受）and 200-day moving-average context（200 日均線背景）.
- `MACRO_HIGHER_LOW` for pullback structure（回檔結構）.
- `CONTROL_TRANSFER_LOOP` for the breakout -> pullback -> Higher Low -> reattack sequence（突破→回檔→更高低點→再攻序列）.
- `meaningful_breakout`, `meaningful_pullback`, `higher_low`, `reattack`, and `prior_control_high_break` in the research evidence-vector evaluator（研究證據向量評估器）.
- `old_control_zone_result`, `candidate_structure_result`, `renewed_expansion`, and `new_local_control_high_break` in `btc_control_transfer_validation.py`.
- Evidence Independence（證據獨立性）rules in `CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md`.

No code delta（程式增量）is necessary. A new `post_event_reattack_structure` field would duplicate existing pre-classified observations without improving False Positive（假陽性）control or analyst interpretation（分析解讀）.

## Interpretation mapping

### Higher High

`HIGHER_HIGH` maps to a confirmed reattack and control-high break, including `new_local_control_high_break = CONFIRMED` where the post-candidate validation contract applies.

It is `CONTROL_TRANSFER_STRENGTHENING_EVIDENCE`（控制權轉移強化證據）only.

It cannot by itself:

- validate Control Transfer（控制權轉移）;
- confirm a bull market（牛市）;
- change Formal Season（正式季節）;
- create an independent evidence vote（獨立證據票）;
- produce `BUY`.

The existing validation sequence still requires a distinct later event, old-control-zone acceptance, preserved candidate structure, and renewed expansion.

### Lower High

`LOWER_HIGH` strengthens a `BEAR_CONTROL_RETAINED`（熊方控制保留）or `CONTROL_TRANSFER_CANDIDATE_FAILED`（控制權轉移候選失敗）interpretation only when the lower-high classification is supported by the surrounding structure.

Existing carriers include:

- `reattack = NOT_CONFIRMED` and `prior_control_high_break = NOT_CONFIRMED` in the research evidence vector;
- `old_control_zone_result = LOST_NOT_RECLAIMED` or `candidate_structure_result = INVALIDATED` in post-candidate validation;
- an observed invalidating lower low（失效性更低低點）, where available.

`new_local_control_high_break = NOT_CONFIRMED` alone is not enough to infer a Lower High（更低高點）or fail a candidate. The existing evaluator intentionally keeps that field non-mandatory, so an absent high break cannot silently become a bearish gate（看空關卡）.

A Lower High（更低高點）cannot by itself:

- change Formal Season（正式季節）;
- create an independent evidence vote（獨立證據票）;
- produce `SELL`.

### Unresolved

Use `UNRESOLVED` when the meaningful reattack has not occurred, the later event is not distinct, event order is unresolved, or the required structure and expansion observations are incomplete.

The interpretation remains pending（未決）, including existing states such as `DEFENSE_HELD_REATTACK_PENDING` and `VALIDATION_PENDING`.

Absence of confirmation is not evidence of a Lower High（更低高點）.

## Pullback quality context

The following may be retained as research-only context（僅研究背景）:

- Higher Low（更高低點）or structural hold（結構守住）;
- resilience under an adverse catalyst（逆風事件下的韌性）;
- sentiment reset with structure hold（情緒重置但結構守住）;
- USDT Dominance（USDT 市占率）as liquidity and pullback-quality context（流動性與回檔品質背景）.

If an adverse event occurs and price still preserves a Higher Low（更高低點）, the analyst may record `STRUCTURE_SURVIVED_ADVERSE_TEST`（結構通過逆風測試）as strengthening context.

These contexts do not create a new score, threshold, evidence vote, or direction signal. USDT Dominance（USDT 市占率）must not become `BTC_DIRECTION_SIGNAL`, `INDEPENDENT_VOTE`, or `FORMAL_THRESHOLD`.

## Evidence independence

Golden Cross（黃金交叉）, 50D（50 日均線）, 200D（200 日均線）, 50W（50 週均線）, Higher Low（更高低點）, Higher High（更高高點）, Lower High（更低高點）, and double top（雙頂）are highly price-derived（高度由價格衍生）.

They must not be counted as multiple independent confirmations of the same price move.

Roles are fixed:

- Golden Cross（黃金交叉）: `EVENT ANCHOR / CONTEXT ONLY`.
- 50W（50 週均線）: `HIGHER-TIMEFRAME ACCEPTANCE CONTEXT ONLY`（高時間尺度接受背景而已）.
- Higher High / Lower High（更高高點／更低高點）: `POST-EVENT STRUCTURAL DISCRIMINATOR`（事件後結構判別器）.

Missing 50W（50 週均線）data is claim-scoped fail-closed（主張範圍封鎖）: it blocks only a 50W acceptance claim, not the entire research record and not a separately supported reattack classification.

## Historical replay

Historical replay（歷史重播）compares event sequence, not win rate:

| Case | Research-input sequence | Interpretation use |
| --- | --- | --- |
| `2014` | Golden Cross -> pullback -> Lower High -> weaker structure | Bear-control-retained comparison（熊方控制保留比較） |
| `2015` | Golden Cross -> pullback -> Lower High -> weaker structure | Candidate-failure comparison（候選失敗比較） |
| `2019` | Golden Cross -> pullback -> Higher High -> continued structure | Bear thesis weakened（熊方論點轉弱） |
| `2023` | Golden Cross -> pullback -> Higher High -> continued structure | Control-transfer strengthening comparison（控制權轉移強化比較） |
| `2026_CURRENT` | Event and pullback context observed; reattack outcome not predetermined | Live unresolved case（即時未決案例） |

Every replay must preserve:

- `FALSE_POSITIVE_RISK`;
- `DETECTION_LATENCY`;
- `SAMPLE_LIMITATION`.

The sample is small and selected around event occurrences. It cannot establish a statistical law.

Percent pullbacks such as 10%, 12%, or 15% are historical case descriptions only. They are not permanent correction thresholds.

Prices such as 67K, 70K, 71K, or 82K are `LIVE_BATTLEFIELD_COORDINATES`（即時戰場座標）only. They are not permanent thresholds and must be refreshed from current evidence before any live analysis.

## Analyst decision rule

The analyst should answer in this order:

1. Was the anchor event observed without treating it as a direction vote?
2. Did a post-event pullback occur?
3. Did the pullback preserve structure, including a Higher Low（更高低點）where supported?
4. Is the reattack a distinct later event and meaningful under the existing pre-classification process?
5. Did the reattack form a Higher High（更高高點）, a Lower High（更低高點）, or remain unresolved（未決）?
6. Does the surrounding control-zone, structure, and expansion evidence support strengthening, retained control, candidate failure, or continued pending status?
7. Which claims are blocked by missing data, and only within what scope?

The answer remains analyst-facing decision support（面向分析者的決策支援）. It is not an automated capital instruction.

## Formal locks

The following remain unchanged:

- six-layer weights（六層權重）`20 / 20 / 17 / 25 / 13 / 5`;
- traffic-light thresholds（燈號閾值）`-60 / -35 / 35 / 60`;
- mNAV semantics（mNAV 語義）;
- Formal Season（正式季節）;
- Season Router（季節路由器）;
- Production approval（正式環境批准）;
- Capital Decision Authority（資本決策權）;
- no seventh layer（不新增第七層）;
- no mechanical DCA multiplier（不建立機械式定投倍數）;
- no automatic `BUY` or `SELL` output.

Authority remains:

`formal_model_authority = NONE`

`formal_weight_authority = NONE`

`formal_threshold_authority = NONE`

`season_transition_authority = NONE`

`action_output = NONE`

`external_action_authority = NONE`

## Decision delta

Golden Cross（黃金交叉）does not decide the market; after the pullback, the first meaningful reattack（第一次有效再攻）and its Higher High / Lower High / Unresolved（更高高點／更低高點／未決）structure sharpen Control Transfer（控制權轉移）interpretation without changing formal authority or creating a trade action.
