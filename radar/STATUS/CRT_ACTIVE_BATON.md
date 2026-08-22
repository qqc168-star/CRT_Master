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
- 已完成：`1`
- 進行中：`1`
- 完成率：`12.5%`
- 目前唯一進行中項目：`#2`
- 目前任務：`ACTUAL_RUNTIME_AUDIT`

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

- [ ] **#2 真正值班 Runtime（執行環境）驗證 — ACTIVE**
  - 從 Windows Scheduled Task（Windows 排程工作）的實際 Action（動作）取得真正 `RepoRoot` 與 `RuntimeRoot`。
  - 驗證真正值班程式的 Git HEAD。
  - 驗證 `evidence/latest.json` 新鮮度與狀態。
  - 驗證 `wake/latest.json` 新鮮度與狀態。
  - 驗證 `notifications/latest.json` 新鮮度與狀態。
  - 驗證 `observations.sqlite3` 持續增加。
  - 驗證最新 BTC 觀測價格與時間戳確實反映實際市場。

- [ ] **#3 Runtime（執行環境）對齊與新鮮循環驗收**
  - 只有 #2 證明版本漂移、資料過期或執行失敗時才施工。
  - 修復後至少完成一個新的真實 observation cycle（觀測循環）。
  - 不得為了追求 PASS（通過）而放寬資料品質或 freshness（新鮮度）政策。

### 第二關：Capital State（資本狀態）

- [ ] **#4 建立 Capital State SSOT（資本狀態唯一真實來源）**
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

## 目前已知阻塞

`ITEM_2_ACTUAL_RUNTIME_NOT_YET_VERIFIED`

已知 Windows Scheduled Task（Windows 排程工作）實際使用：

`C:\Users\maxwe\CRT_EvidenceRunner_018c263d_git`

其 RuntimeRoot（執行環境根目錄）為：

`C:\Users\maxwe\CRT_Runtime`

第一次唯讀稽核錯誤檢查：

`C:\Users\maxwe\CRT_EvidenceRunner`

因此在取得 branch（分支）資訊時產生 `Null`（空值）錯誤。

此錯誤屬於 audit script（稽核程式）路徑假設錯誤。

目前尚未證明真正值班 Runtime（執行環境）故障，也尚未證明其版本與 current main（目前主分支）一致。

所以 #2 維持未完成。

## 下一個唯一有效動作

針對 Windows Scheduled Task（Windows 排程工作）實際配置的：

`C:\Users\maxwe\CRT_EvidenceRunner_018c263d_git`

進行一次 read-only audit（唯讀稽核）。

只驗證：

- Git HEAD
- Evidence Pack（證據包）
- Wake（喚醒訊號）
- Notice（通知檔）
- Observation DB（觀測資料庫）
- 最新 BTC 觀測

不得在該稽核中修改 Git、Runtime（執行環境）、Scheduled Task（排程工作）或任何正式 CRT 規則。

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