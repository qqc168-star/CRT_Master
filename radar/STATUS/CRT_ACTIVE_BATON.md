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
- 已完成：`3`
- 進行中：`1`
- 完成率：`37.5%`
- 目前唯一進行中項目：`#4`
- 目前任務：`CAPITAL_STATE_SSOT`

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

- [ ] **#4 建立 Capital State SSOT（資本狀態唯一真實來源） — ACTIVE**
  - 完整追蹤持倉。
  - 可用現金。
  - 資產角色。
  - 三段式資本計畫。
  - 每一段的預算、狀態與有效條件。

- [ ] **#5 建立使用者確認的 Execution Update（成交更新）**
  - 只有使用者明確確認成交，機器才可把該段標記為已執行。
  - 不得因價格觸及、掛單存在或模型推測而自行認定成交。

- [ ] **#6 建立 Plan Drift / Price Escape（計畫偏離／價格逃逸）偵測**
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

## 目前已知阻塞

`ITEM_4_CAPITAL_STATE_SSOT_NOT_YET_IMPLEMENTED`

目前雷達可以自主觀察市場並產生 Evidence / Wake / Notice（證據／喚醒／通知），但尚無一份完整且單一的 Capital State SSOT（資本狀態唯一真實來源）可讓系統可靠知道：

- 使用者目前實際持倉
- 可用現金
- 各資產角色
- 三段式資本計畫
- 各段預算
- 各段目前狀態
- 各段仍有效的條件

因此市場價格即使已經逃離原計畫區間，CRT 仍無法可靠知道哪一段已完成、哪一段仍待命，以及剩餘資本應重新如何部署。

## 下一個唯一有效動作

處理 #4 Capital State SSOT（資本狀態唯一真實來源）。

施工前先盤點 current main（目前主分支）既有 private portfolio（私人投資組合）結構與所有使用點，優先擴充既有結構，不建立平行的第二套 Portfolio（投資組合）系統。

#4 本身只建立「最新資本狀態的可靠機器來源」。

不得在 #4：

- 自行推定任何交易已成交
- 自動修改持倉
- 建立交易執行權限
- 實作 Price Escape（價格逃逸）判斷；該能力屬 #6
- 實作 GPT 主動喚醒；該能力屬 #7

## 暫緩工作

在本 Baton（接力棒）達成 `8 / 8` 前，以下工作不主動推進，除非它們被證明直接阻塞本任務：

- Formal Season Router（正式季節路由器）恢復
- Formal Season Input Binding（正式季節輸入綁定）
- 20-run maturity（20 次成熟度）
- 新指標
- 新 Overlay（覆蓋分析）
- 新 Dashboard（儀表板）
- 新流程型治理結構

## 防迷航規則

新的 CRT 工程聊天室開始時：

1. 先讀 GitHub current `main`。
2. 再讀本檔。
3. 先報告：最初工作目標、總項目數、已完成數、完成率、目前唯一工作、阻塞與下一刀。
4. 不得依聊天室記憶自行跳過未完成項目。
5. 每次只推進目前唯一進行中項目。
6. 只有驗收項目狀態、真實阻塞或下一個有效動作改變時，才更新本 Baton。
7. 普通 Git HEAD 移動本身不代表 Baton 過期。

## 正式鎖

本 Baton 不是新的正式模型，也不具有投資門檻權限。

以下維持不變：

- 六層權重：`20 / 20 / 17 / 25 / 13 / 5`
- 燈號閾值：`-60 / -35 / 35 / 60`
- 未加限定的 `mNAV`：`Diluted Equity mNAV`
- Production approval（正式生產批准）：不變
- External Action Authority（外部行動權限）：`NONE`
- 使用者保有最終資本決定權