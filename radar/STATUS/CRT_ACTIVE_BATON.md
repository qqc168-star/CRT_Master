# CRT Active Baton（CRT 主動接力棒）

## 最初工作目標

在使用者不需要反覆手動「點燈」的情況下，讓 CRT 持續觀察市場。

當 BTC 或追蹤資產出現與資本決策相關的重大變化時，系統必須能：

`市場 → 自動蒐集 → 驗真 → 計算與比較 → Evidence Pack → 讀取最新資本狀態與三段計畫 → 偵測計畫偏離 → 喚醒 GPT → GPT 重新分析 → 主動通知使用者 → 使用者決定`

GPT（大廚）可以提出買入、賣出、續抱、等待、輪動或重新定價建議。

任何實際交易仍只由使用者決定與執行。

- External Action Authority（外部行動權限）: `NONE`
- Capital Decision Authority（資本決策權限）: `USER_ONLY`
- Production（正式生產）: `NOT_APPROVED`

## 固定進度

- 總驗收項目：`8`
- 已完成：`6`
- 進行中：`1`
- 完成率：`75%`
- 目前唯一進行中項目：`#7`
- 目前任務：`GPT_WAKE_HANDOFF`

完成率只使用：

`已完成項目 / 8`

不得因新增研究想法自行增加分母。

新增、刪除或重定義這 8 項必須由使用者明確批准。

## 三大關／八個驗收項目

### 第一關：Live Radar（實戰雷達）

- [x] **#1 Windows 背景排程心跳驗證**
  - `CRT-Observation-History` 已找到。
  - 狀態為可執行。
  - 最近一次執行完成。
  - `LastTaskResult = 0`。
  - 此項只證明 Windows 排程有執行，不代表完整市場資料鏈已驗收。

- [x] **#2 真正值班 Runtime（執行環境）驗證 — COMPLETE WITH FINDINGS**
  - 從 Windows Scheduled Task（Windows 排程工作）的實際 Action（動作）取得真正 `RepoRoot` 與 `RuntimeRoot`。
  - 驗證真正值班程式的 Git HEAD。
  - 驗證 `evidence/latest.json` 新鮮度與狀態。
  - 驗證 `wake/latest.json` 新鮮度與狀態。
  - 驗證 `notifications/latest.json` 新鮮度與狀態。
  - 驗證 `observations.sqlite3` 持續增加。
  - 驗證最新 BTC 觀測價格與時間戳確實反映實際市場。

- [x] **#3 Runtime（執行環境）對齊與新鮮循環驗收 — COMPLETE**
  - 只有 #2 證明版本漂移、資料過期或執行失敗時才施工。
  - 修復後至少完成一個新的真實 observation cycle（觀測循環）。
  - 不得為了追求 PASS（通過）而放寬資料品質或 freshness（新鮮度）政策。

### 第二關：Capital State（資本狀態）

- [x] **#4 建立 Capital State SSOT（資本狀態唯一真實來源） — COMPLETE**
  - 完整追蹤持倉。
  - 可用現金。
  - 資產角色。
  - 三段式資本計畫。
  - 每一段的預算、狀態與有效條件。

- [x] **#5 建立使用者確認的 Execution Update（成交更新） — COMPLETE**
  - 只有使用者明確確認成交，機器才可把該段標記為已執行。
  - 不得因價格觸及、掛單存在或模型推測而自行認定成交。

- [x] **#6 建立 Plan Drift / Price Escape（計畫偏離／價格逃逸）偵測 — COMPLETE**
  - 市場價格脫離原進場區時不得沉默。
  - 必須判斷原計畫是否仍有效。
  - 必須要求重新驗收市場結構。
  - 必須能提出維持原價、暫停、重新定價、保留後續資金或撤退等建議。
  - 不得自動下單。

### 第三關：GPT Wake（GPT 喚醒）

- [ ] **#7 Evidence / Wake → GPT（證據／喚醒 → GPT）主動交接**
  - 合格重大異動必須能觸發 GPT 重新分析。
  - GPT 分析必須使用最新市場證據與最新 Capital State（資本狀態）。
  - 相同狀態不得重複通知轟炸。
  - 不得執行交易。

- [ ] **#8 End-to-End Live Acceptance（端到端實戰驗收）**
  - 真實市場變化被偵測。
  - 證據完成驗真。
  - 最新 Capital State 被載入。
  - 未完成三段計畫被重新檢查。
  - 若計畫已偏離，產生重新定價或等待判斷。
  - GPT 產生分析與資本建議。
  - 使用者收到一次主動通知。
  - 沒有重複通知風暴。
  - 沒有外部交易或資金操作。

## #2 驗收結果

`AUDIT_COMPLETE_REPAIR_REQUIRED`

已驗證：

- Windows Scheduled Task（Windows 排程工作）持續正常執行。
- Observation DB（觀測資料庫）持續增加。
- 最新 BTC 觀測可正常寫入。
- `2026-08-22 21:13 +08:00` 最新 BTC 觀測約為 `77235.01`。
- 真正值班 Runtime（執行環境）的 Git HEAD 與 current GitHub main（目前主分支）不同。

因此：

- #2：`COMPLETE WITH FINDINGS`
- 問題移交 #3。
- 不把版本漂移誤判成資料蒐集完全失效。

## #3 驗收結果

`RUNTIME_ALIGNMENT_AND_FRESH_CYCLE_PASS`

已驗證：

- 真正值班 Runtime（執行環境）舊 Git HEAD：
  `018c263d60d660804504f3c4683ac679daf4f466`
- 對齊後 Git HEAD：
  `8ae27142bf63dd491aa9a729860912c211fa69a2`
- Runtime working tree（執行環境工作樹）乾淨。
- Observation DB（觀測資料庫）原地保留並在新循環後繼續前進。
- Evidence Pack（證據包）在新循環後刷新。
- Wake（喚醒訊號）存在。
- Notice（通知檔）存在。
- Windows Scheduled Task（Windows 排程工作）設定未修改。
- stash（暫存修改）未碰。
- `reset`（重設）未使用。

因此第一關 Live Radar（實戰雷達）三項全部完成。

## #4 驗收結果

`CAPITAL_STATE_LIVE_ACCEPTANCE_PASS`

已驗證：

- 真正值班 Runtime（執行環境）已對齊 current GitHub main（目前主分支）。
- 使用者確認的 holdings（持倉）已由 local-only Capital State（僅本機資本狀態）驗證。
- 使用者確認的 capital policy（資本政策）已驗證。
- 三段式 Capital Plan（資本計畫）已存在且符合契約。
- 目前計畫可明確表達 `WAIT`（等待），不需要捏造買入或賣出價格。
- 三段狀態與 validity conditions（有效條件）已通過契約驗證。
- 新的真實 observation cycle（觀測循環）已完成。
- Evidence Pack（證據包）已刷新並成功載入最新 Capital State（資本狀態）與三段式計畫。
- 實際私人持倉、現金與計畫金額仍只存在 local-only private profile（僅本機私人設定），不寫入 Git 狀態檔。
- External Action Authority（外部行動權限）維持 `NONE`。
- Scheduled Task（排程工作）設定未修改。
- stash（暫存修改）未碰。

因此：

- #4：`COMPLETE`
- Capital State SSOT（資本狀態唯一真實來源）已具備實戰可讀能力。
- 工作移交 #5 Execution Update（成交更新）。

## #5 驗收結果

`EXECUTION_UPDATE_LIVE_ACCEPTANCE_PASS`

已驗證：

- 真正值班 Runtime（執行環境）已對齊 current GitHub main（目前主分支）。
- Execution Update（成交更新）只接受使用者明確確認的成交。
- `WAIT`（等待）計畫不得被自行標記成交。
- stale state（過期狀態）會 fail-closed（失敗關閉）。
- duplicate update（重複更新）會被阻擋。
- 成交更新可可靠更新 Capital State（資本狀態）。
- 成交更新可更新對應 tranche（批次）狀態。
- pre-execution backup（成交前備份）可建立。
- 更新後的 Capital State（資本狀態）可被 Evidence Pack（證據包）重新載入。
- 使用隔離 synthetic fixture（合成測試資料）完成端到端驗收。
- 真實 private portfolio（私人投資組合）未被測試修改。
- 真實 Evidence Pack（證據包）未被測試修改。
- Windows Scheduled Task（Windows 排程工作）設定未修改。
- External Action Authority（外部行動權限）維持 `NONE`。
- stash（暫存修改）未碰。

因此：

- #5：`COMPLETE`
- Execution Update（成交更新）已具備實戰可用能力。
- 工作移交 #6 Plan Drift / Price Escape（計畫偏離／價格逃逸）。

## #6 驗收結果

`PLAN_DRIFT_PRICE_ESCAPE_LIVE_ACCEPTANCE_PASS`

已驗證：

- PR #48（合併請求48）已合併至 current GitHub main（目前主分支）。
- merged main SHA（合併後主分支提交）：
  `927be1ec950b67db9d640de249fda153e026d758`
- 真正值班 Runtime（執行環境）已對齊上述 current main（目前主分支）。
- 新的真實 observation cycle（觀測循環）已完成。
- Evidence Pack（證據包）已刷新。
- Plan Drift（計畫偏離）已正式寫入 Evidence Pack（證據包），並納入 `evidence_pack_hash`。
- 真實 Capital Plan（資本計畫）：
  `ATTACK_CAPITAL_WAIT`
- 真實 Plan Drift（計畫偏離）結果：
  `STABLE`
- pending tranches（待執行批次）：`3`
- satisfied conditions（成立條件）：`3`
- violated conditions（違反條件）：`0`
- blocked conditions（阻塞條件）：`0`
- `reanalysis_required = false`
- 條件來源正確解析至 Capital State（資本狀態）。
- 未綁定或多重來源條件採 fail-closed（失敗關閉）。
- 條件真正被違反時才形成 `REANALYSIS_REQUIRED`（需要重新分析）。
- 不把價格觸及自行視為成交。
- 不自動修改 Capital State（資本狀態）。
- 不自動修改 tranche（批次）。
- 不自動下單。
- 真實 private portfolio（私人投資組合）hash（雜湊值）未變。
- Windows Scheduled Task（Windows 排程工作）設定未修改。
- Runtime working tree（執行環境工作樹）乾淨。
- stash（暫存修改）未碰。
- External Action Authority（外部行動權限）維持 `NONE`。

因此：

- #6：`COMPLETE`
- Live Action Loop（實戰行動迴圈）完成度：`6 / 8 = 75%`
- 工作正式移交 #7 GPT Wake（GPT 喚醒）。

## 目前已知阻塞

`ITEM_7_GPT_WAKE_HANDOFF_NOT_YET_IMPLEMENTED`

目前系統已能可靠完成：

`市場資料`
→ `Evidence Pack（證據包）`
→ `最新 Capital State（資本狀態）`
→ `未完成 Capital Plan（資本計畫）`
→ `Plan Drift（計畫偏離）條件解析`
→ `STABLE / BLOCKED / REANALYSIS_REQUIRED`

但目前仍缺少 #7 的正式主動交接：

`合格重大異動`
→ `Wake（喚醒訊號）`
→ `GPT 讀取最新 Evidence Pack（證據包）`
→ `GPT 重新分析`
→ `形成一次可通知使用者的決策建議`

在 #7 完成前：

- `REANALYSIS_REQUIRED`（需要重新分析）不得直接等同交易指令。
- 不得由機器自行修改持倉、計畫價格或資金配置。
- 不得自動下單。
- 相同狀態不得造成重複通知風暴。
- GPT（大廚）必須讀取最新 Evidence Pack（證據包）與最新 Capital State（資本狀態）後才重新分析。
- External Action Authority（外部行動權限）維持 `NONE`。
- Production approval（正式生產批准）維持不變。

## 下一個唯一有效動作

處理 #7 Evidence / Wake → GPT（證據／喚醒 → GPT）主動交接。

#7 只建立：

`合格重大異動`
→ `可靠 Wake（喚醒）`
→ `GPT 重新讀取最新證據與資本狀態`
→ `重新分析`
→ `形成一次主動通知`

不得在 #7：

- 自動認定成交
- 自動修改使用者持倉
- 自動下單
- 自動移動資金
- 修改正式模型、六層權重、燈號閾值或 mNAV 語義
- 修改 Production approval（正式生產批准）
- 修改 External Action Authority（外部行動權限）
