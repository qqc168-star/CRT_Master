# CRT MSTR／ASST GPT Wake Closure V0.1

## 基線

- Public GitHub current `main`: `4fe185887044abf1f378354414cbe417fa7247cb`
- Local construction branch: `agent/mstr-asst-gpt-wake-closure-v0.1`
- External Action Authority: `NONE`
- Capital Decision Authority: `USER_ONLY`
- Production: `NOT_APPROVED`

## 已閉合的軟體路徑

`MSTR／ASST complete-session OHLCV`
→ `same-close-clock BTC`
→ `daily options snapshot`
→ `Market Health Evaluator`
→ `Reanalysis Wake Fusion`
→ `Evidence Pack hash`
→ `Plain Language GPT Reanalysis Notice`
→ `GPT Handoff Gate`
→ `Minimized Bridge Payload`
→ `Three-Army Commander required analysis behavior`
→ `Durable Local Outbox`

### Full-Day Market Intake

- 排除尚未收盤的 IBKR daily bar。
- 支援正常 16:00 ET 與明確傳入的提前收盤日。
- 計算 latest／previous RVOL20、1 日／5 交易日報酬。
- BTC 只接受與股票 session close 完全相同的時間點。
- BTC 時鐘不合格只封鎖 relative-BTC claim，不摧毀有效 OHLCV。

### Options Daily Snapshot

- 分開保存 aggregate volume 與 contract-level OI／IV 的時間與狀態。
- Put/Call volume ratio、covered Put/Call OI ratio 與 top OI strikes 可用。
- LIMITED coverage 只可聲稱 `COVERED_CONTRACTS_ONLY`。
- Dealer Gamma／GEX 維持 `BLOCKED`；`OI + IV` 不得冒充 dealer positioning。
- Short Interest 維持 `BLOCKED`。

### Market Health Evaluator

只有下列四個確定性事件可以自動要求 GPT 重新分析：

- `FALSE_BREAKOUT_CONFIRMED`
- `FIRST_DEFENSE_BREACHED`
- `TACTICAL_INVALIDATION_BREACHED`
- `BTC_PER_DILUTED_SHARE_DECREASED`

Relative BTC、Put/Call 變化與 strike OI 變化仍是 `OBSERVATION_ONLY`。
Attack／Defense／Invalidation lines 必須來自 `THREE_ARMY_COMMANDER` 且
`approval_state = APPROVED`；機器不得自己畫線。

### Wake／Evidence／GPT／Commander

- Market Health 在 Evidence Pack hash 形成前寫入。
- Wake reason 使用 `MSTR:<reason>`／`ASST:<reason>`，保留資產身分。
- 同資產、同語義事件即使 Evidence Pack hash 更新仍去重。
- 不同資產的同名事件形成不同 GPT handoff episode。
- Minimized Bridge Payload 含 Market Health，但不含 raw private context。
- GPT required inputs 明確要求最新 Market Health 與最新核准 Commander lines。
- GPT required behavior 明確要求 Three-Army Commander Doctrine 與通知裁決。
- Wake 只形成 `GPT_JUDGMENT_PENDING`；不等於使用者通知。

## 驗收邊界

### Strategy Ledger reported-observation binding

MSTR issuer ratio 的預設來源為 Strategy official `/ledger`，Notes 是
`METRIC_SEMANTIC_AUTHORITY`，SEC 保留 `DISCLOSURE_AND_CAPITAL_EVENT_AUTHORITY`。
既有 SEC MSTR collector 保留，以 `--mstr-source SEC` 明確執行 audit/cross-check；
ASST 仍使用原 SEC paired-state 路徑。來源契約只更新 issuer ratio entry。

Ledger adapter 依唯一 `Reported / BTC / ADSO ('000)` 表頭取同列 BTC 與
ADSO × 1,000，排除 totals、缺 ADSO 的歷史列，按 reported date 排序後取
最新兩個相鄰有效 observations；日期衝突、未來日期、單位／表頭歧義均拒收。
`--raw-archive-dir` 可指定 repo 外原始證據目錄，CLI 預設保存在 output 旁的
`raw`；普通 HTTPS GET 使用非私人 User-Agent，不轉送 SEC contact identity。

每列保留 `reported_date`、`reported_at_ms`、`retrieved_at_ms`、
`first_seen_at_ms`、`source_url` 與 raw SHA-256。`reported_at_ms` 僅是
`REPORTED_DATE_UTC_MIDNIGHT_SORT_KEY_ONLY`；first-seen 是這次本機抓取首次看見
該 snapshot 的時間，並非出版／揭露時鐘，也不宣稱歷史 point-in-time 可回放。
`time_semantic = REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME` 永久保留。

2026-09-21 與 2026-09-28 reported observations 的 BTC/ADSO 約下降 0.129018%，
只支持 `ADJACENT_REPORTED_BTC_PER_ADSO_DECREASED`。既有
`MSTR:BTC_PER_DILUTED_SHARE_DECREASED` 仍僅要求 GPT reanalysis；
不是 formal Company Health deterioration，也不產生分數、燈號或交易。
reported clocks、來源 URL/hash、comparison horizon、`OBSERVATION_ONLY` 與
`machine_execution = FORBIDDEN` 在 Market Health、Evidence Pack、GPT bridge
保留，沿用既有下游接線，不新增引擎。

**永久 CT 邊界：`NOT_CT_BOUND / ADSO_EFFECTIVE_TIME_UNRESOLVED`。**
此證據不得供 Treasury Company CT 或 formal mNAV 使用；reported／retrieval／
first-seen 不得偽裝 effective/disclosure clocks。完整 live runtime 仍須五項
原來源證據，包含真正 `APPROVED` Commander lines；Ledger ratio 的真實觀察
驗收與離線五來源回歸必須分開描述，不得以 fixture 補足 live 前置缺口。

### #7 GPT Wake

`MSTR_ASST_EQUITY_HEALTH_SOFTWARE_PATH_CLOSED`

本地軟體、雜湊、去重、Evidence Pack、GPT handoff、Bridge payload 與 outbox
路徑已閉合。External transport 仍未 claim 或 delivery，因此不得把本結果寫成
unattended GPT delivery 或 user notification 已完成。

### #8 End-to-End Live Acceptance

`OFFLINE_PREFLIGHT_PASS_LIVE_NOT_EXECUTED`

離線 fixture 已證明：股票事件可穿過完整鏈條，讀取最新 Capital State，形成一次
GPT handoff，重複狀態被抑制，且沒有交易或外部動作。真正 live acceptance 仍需：

1. 值班 Runtime 產生最新 validated Market Health 本機快照。
2. 值班入口實際帶入 `--mstr-asst-market-health`。
3. 使用者另行批准的 GPT transport／notification 路徑完成一次 delivery receipt。
4. 驗證沒有通知風暴、沒有交易、EAA 仍為 `NONE`。

在上述 live evidence 出現前，CRT Active Baton 不得從 `6 / 8` 誤升為 `8 / 8`。


## Independent issuer observation -> GPT closure (post-PR120)

The additive `issuer_ratio_observation` Evidence Pack section is independent of
`asset_facts` / `issuer_facts`, Treasury Company CT, formal mNAV and Company Health.
`build_issuer_ratio_observation()` validates the existing sealed issuer proof with
the existing source validator and reuses `issuer_ratio_observation()`; it does not
require the other four full Market Health proofs. Full Market Health still requires
all five sources, including approved Commander lines.

Use the existing collector output with the daily runner's optional
`--issuer-ratio-proof <local-proof.json>` input. Without this input existing runs
retain their behavior. The source proof and its clocks/hash/authority must validate;
invalid proof, same-row ratio mismatch, future observation and invented Ledger
effective/disclosure clocks fail closed.

A decrease produces `MSTR:BTC_PER_DILUTED_SHARE_DECREASED` from
`MSTR_ISSUER_RATIO_OBSERVATION` (or the ASST counterpart), for GPT reanalysis only.
It does not infer Company Health deterioration, scores, lights or any trade action.
Re-fetching the same pair is deduplicated; changed facts or new adjacent reported
pairs have distinct semantic identities, independent of retrieval timestamps.

The minimized bridge has a separate literal `issuer_ratio_observation` section:
paired reported dates, BTC, ADSO, BTC/share, percent change, current source/hash,
retrieval/first-seen clocks and all Ledger warnings remain explicit. Full previous
and current clock/source provenance stays in the hash-bound Evidence Pack. Equal
ASST source URL/hash fields may be shared with explicit `BOTH_SEC_PAIRED_STATES`
scope; ASST's previous/current SEC effective clocks are preserved. The existing
16,384-byte limit, privacy rules and action authority remain unchanged.

`REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME`, `ADJACENT_REPORTED_OBSERVATIONS`,
`NOT_CT_BOUND`, `ADSO_EFFECTIVE_TIME_UNRESOLVED`, `OBSERVATION_ONLY` and
`machine_execution = FORBIDDEN` remain mandatory. This lane can reach
`GPT_HANDOFF_READY` even when the formal pack is blocked by separate source gaps.
A ready local bridge is not completed GPT judgment, notification or execution.

Deterministic tests: `tests.test_issuer_observation_gpt_closure`, alongside existing
Ledger, Market Health, wake fusion and GPT handoff regression tests. Live acceptance
uses fresh ordinary-HTTPS Ledger / SEC proof, real market/history inputs and the
actual daily runner, with private-safe audit artifacts outside the repository;
fixtures never substitute for live evidence.
