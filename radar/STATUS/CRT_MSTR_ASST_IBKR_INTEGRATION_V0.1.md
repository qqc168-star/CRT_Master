# CRT MSTR／ASST × IBKR GPT Wake Integration V0.1

## 整合基線

- Public GitHub current `main`: `4fe185887044abf1f378354414cbe417fa7247cb`
- MSTR／ASST GPT Wake parent: `046e24069eb581f9ee1064a32ab45da3cf696ac7`
- IBKR Gate 6C-3 parent: `a4c9463296752932b3799a5c85d4a9fd63f1c1f7`
- Integration branch: `agent/mstr-asst-ibkr-gpt-wake-integration-v0.1`
- External Action Authority: `NONE`
- Capital Decision Authority: `USER_ONLY`
- Production: `NOT_APPROVED`

兩條施工線保留原 branch／worktree，不在來源分支上互相覆寫。

## 合流結果

共同修改的接線檔為：

- `crt_radar/__init__.py`
- `evidence_pack.py`
- `plain_language_notice.py`
- `reanalysis_wake.py`

`__init__.py` 與 `reanalysis_wake.py` 自動合併；`evidence_pack.py` 與
`plain_language_notice.py` 手工整合並保留雙方語義。

整合後：

1. 同一 Evidence Pack 可同時攜帶 IBKR premarket live-market handoff／battle map
   與已驗證的 MSTR／ASST Market Health。
2. Evidence Pack hash 在上述兩個證據表面寫入後形成。
3. Commander observation 與 MSTR／ASST Market Health 可同時成為 Wake source。
4. Plain-language notice 同時揭露 equity-health 與 Commander line event，仍只要求
   GPT 重新分析。
5. IBKR observation journal、Gate 6A checkpoint、事件去重與 GPT handoff 保持原語義。
6. 價格到線、Market Health Wake 與 GPT Handoff 都不形成交易權限或資金動作。

## 驗證

- MSTR／ASST × IBKR 新增交會回歸測試：`2 / 2 PASS`
- 整合後完整 Python 套件：`637 / 637 PASS`
- Read-only surface assertion: `PASS`
- Conflict marker scan: `PASS`
- Git diff check: `PASS`

## 驗收邊界

### #7 GPT Wake

`INTEGRATED_SOFTWARE_PATH_CLOSED`

Market Health 與 Commander observation 均可穿過 Evidence Pack、Reanalysis Wake、
plain-language notice 與 GPT Handoff Gate。Durable local handoff／outbox 可以形成，
但 External transport 仍為 `transport_performed = false`；不得聲稱使用者通知已送達。

### #8 End-to-End Live Acceptance

`INTEGRATED_OFFLINE_PASS_LIVE_RERUN_REQUIRED`

IBKR parent `a4c9463` 已有 moving-market Gate 6C-3 acceptance evidence；本整合提交
未冒充該舊證據已在新 commit 上重跑。要把整合線升為 live acceptance，必須以本整合
commit 再完成一次：

1. IBKR live market-data proof 與 verified plan identity 檢查。
2. Moving-market observation → journal → Gate 6A state → Wake 的實際事件。
3. 同次 Evidence Pack 帶入最新 MSTR／ASST Market Health。
4. GPT handoff receipt、去重與 restart replay 驗證。
5. 全程確認沒有下單、持倉、資金或未授權通知動作。

在本整合 commit 的 live evidence 出現前，不得把 #8 標成完成。
