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
