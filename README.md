# CRT_Master — North Star Bootloader

## What CRT is

CRT is a read-only decision-support system for five questions:

1. What BTC season are we in?
2. Is market weather improving or worsening?
3. What forces dominate?
4. What role should each tracked asset play?
5. Should capital BUY, SELL, HOLD, WAIT, or ROTATE?

North Star: **Automation prepares evidence. GPT creates judgment. Human commits capital.**

## Boot sequence for a fresh GPT

1. Treat current `main` as the only engineering truth.
2. Read `CRT_CORE_CONTRACT.md`.
3. Read `CRT_EVIDENCE_PACK_CONTRACT.md`.
4. Read `CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md` for the GPT（分析主廚） reasoning sequence（推理順序）, evidence-independence rules（證據獨立性規則）, regime synthesis（市場狀態整合）, asset-role translation（資產角色轉譯）, portfolio interaction（投資組合互動）, and capital-judgment requirements（資本判斷要求）.
5. Read `CRT_SEASON_THREE_ARMY_COMMANDER_DEPLOYMENT_DOCTRINE_V0.1.md` for the non-formal separation（非正式分工） between Season（季節） strategic risk posture（戰略風險姿態）, Bull Foundation（牛市地基） transition credibility（轉換可信度）, and Three-Army Commander Map（三軍統帥地圖） tactical deployment（戰術部署）.
6. Read `radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md` for preserved formal locks.
7. Inspect current executable code and tests before claiming a capability exists.
8. Read the single `CRT Active Baton` working bookmark if one exists.
9. Report: North Star, role boundaries, governance locks, verified capabilities, BLOCKED gaps, current objective, and next effective action.

Never reconstruct missing formal implementation from old chats or memory. If the formal basis is absent, report `BLOCKED`.

## 永久使用者語言規則｜User-facing Language Rule（對使用者語言規則）

- CRT（第一顆比特幣決策研究體系）對使用者輸出中，每次出現 English term or acronym（英文術語或縮寫）時，都必須立即附上繁體中文註解。
- `Code`（程式碼）、`commands`（命令）、`paths`（路徑）、`identifiers`（識別碼）、`field names`（欄位名稱）與其他 machine-readable literals（機器可讀原始字串）必須保持原樣；中文說明放在原始字串外。
- 新聊天室必須從 current `main`（目前主分支）恢復此規則，不得要求使用者重新說明。

## 工程工作慣性｜Engineering Workflow Habit（工程流程習慣）

- 保留 pre-construction plan（施工前規劃）與 complete regression testing（完整回歸測試）；先規劃，再施工，施工後完整驗證。
- `Simplicity first`（簡單優先）；process overhead（流程負擔）不得自行長成新的 gate（關卡）。

### 1. 聊天室目錄治理｜Chat Directory Governance（聊天室目錄治理）

- ChatGPT Project（ChatGPT 專案）中的聊天室主要承載 research（研究）、evidence intake（證據輸入）、hypothesis（假說）、CRT judgment（CRT 判斷）、decision design（決策設計）與 engineering design（工程設計）；聊天室不是 Engineering SSOT（工程唯一真實來源）。
- 定期封存或整併已完成、已被取代或內容重複的聊天室，只保留仍持續有新資料、持續需要 GPT 推理／決策，或仍有未完成工程工作的必要分支工作線。
- GitHub current `main`（目前主分支）永遠是唯一 Engineering SSOT（工程唯一真實來源）；不得從舊聊天室、舊 SHA 或記憶重建 current engineering state（目前工程狀態）。

### 2. GPT 先完成工作骨架，再交 Codex｜GPT-First, Codex-After-Spec（先規格、後施工）

- 為兼顧 development efficiency（開發效率）與節省 Work / Agentic usage（工作模式／代理型功能額度），預設先在一般 GPT Chat（一般 GPT 聊天室）完成：
  - data collection（資料蒐集）
  - evidence intake（證據輸入）
  - hypothesis formation（假說形成）
  - problem definition（問題定義）
  - work skeleton（工作骨架）
  - data contract（資料契約）
  - acceptance criteria（驗收條件）
  - construction boundary（施工邊界）
  - Ready-to-Implement Delta（可實作增量）
- 只有上述工作已具體到足以施工後，才交給 Codex（程式施工代理）進行 repository work（版本庫施工）。
- Codex（程式施工代理）每次新工程任務開始前，仍必須重新讀 current `main`（目前主分支），不得沿用舊 BASE SHA。
- 避免讓 Codex（程式施工代理）一邊探索尚未釐清的需求、一邊修改程式，再因需求翻轉而重工。

### 3. Work / Codex 額度耗盡時的人工工程備援｜Manual Engineering Fallback（人工工程備援）

- 當 Work（工作模式）或 Codex（程式施工代理）額度耗盡、不可用，或不值得消耗代理型額度時，工程不得因此停擺。
- 回到一般 GPT Chat（一般 GPT 聊天室），由 GPT 負責理解、推理、產生或修改 Code（程式碼）、產生 PowerShell（命令列）與 Git（版本控制）施工指令，並設計 Test（測試）與驗收方法。
- 使用者審視後人工貼入 PowerShell（命令列），實際施工路徑固定為：
  `Local Git -> isolated worktree -> modify -> test -> Commit -> Push -> PR`
- 不得 apply / pop / drop / rewrite（套用／彈出／刪除／改寫）既有 stash（暫存修改）。
- ChatGPT GitHub App（ChatGPT GitHub 應用程式）只用於 read / search / verify（讀取／搜尋／驗證）current `main`；不得用它進行 Branch / Commit / File write（分支／提交／檔案寫入）。
- ChatGPT GitHub App 若遇 `HTTP 403`，不得反覆重試，也不得視為 CRT（前行者研究院）程式故障。
- Patch（補丁）只在實際 Git 寫入路徑失敗時作備援，不作正常施工流程。
- `Review Pack / ZIP / Test Report`（檢核包／壓縮檔／測試報告）不得成為每刀固定產物。
- `Formal Release`（正式發布）、`Migration`（遷移）或 special isolated integration（特殊隔離整合）時，才依實際需要增加打包。
## Authority boundary

- Production: `NOT_APPROVED`
- External Action Authority: `NONE`
- No trading, account access, or fund movement authority
- Approved formal models, weights, thresholds, mNAV semantics, and governance locks remain unchanged unless explicitly superseded by later formal approval
- Existing stash must not be applied, popped, dropped, or rewritten without explicit instruction

## Current architecture principle

Build a lean evidence pipeline that serves the GPT analyst:

`World -> Collect -> Validate -> Normalize -> Calculate -> Compare -> Detect -> Distill -> CRT Evidence Pack -> GPT Analysis -> User Decision`

Do not expand infrastructure unless it materially improves North Star decisions or evidence integrity.

## Resurrection PASS

A fresh GPT passes resurrection only if, using `main` plus the single Baton, it can correctly recover:

- CRT North Star
- Automation / GPT / User roles
- formal governance boundaries
- verified current capabilities
- BLOCKED gaps
- current objective
- next effective action

If it cannot, repository knowledge is incomplete.
