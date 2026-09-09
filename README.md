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
  `Local Git -> isolated worktree -> modify -> test -> Commit -> Push -> PR -> Merge -> post-merge verification`
- 不得 apply / pop / drop / rewrite（套用／彈出／刪除／改寫）既有 stash（暫存修改）。
- ChatGPT GitHub App（ChatGPT GitHub 應用程式）只用於 read / search / verify（讀取／搜尋／驗證）current `main`；不得用它進行 Branch / Commit / File write（分支／提交／檔案寫入）。
- ChatGPT GitHub App 若遇 `HTTP 403`，不得反覆重試，也不得視為 CRT（前行者研究院）程式故障。
- Patch（補丁）只在實際 Git 寫入路徑失敗時作備援，不作正常施工流程。
- `Review Pack / ZIP / Test Report`（檢核包／壓縮檔／測試報告）不得成為每刀固定產物。
- `Formal Release`（正式發布）、`Migration`（遷移）或 special isolated integration（特殊隔離整合）時，才依實際需要增加打包。
### 4. 一次授權、自主閉環｜One-Go Autonomous Closure（一次授權自主閉環）

- 當 objective（目標）與 construction boundary（施工邊界）已清楚，使用者的 `GO / 開工 / 做完 / 繼續 / 現在來搞` 即視為該任務邊界內的完整 engineering authorization（工程授權）。
- 完整工程鏈預設包含：
  `inspect -> diagnose -> modify -> test -> debug -> regression -> Commit -> Push -> PR -> Merge -> post-merge verification`
- 不得把正常工程鏈拆成逐步 permission requests（權限請求）；不得再要求使用者逐次批准檢查、修正、測試、Commit（提交）、Push（推送）、PR（合併請求）或 Merge（合併）。
- Agent（代理）必須自行完成：
  `detect -> diagnose -> repair -> validate -> retest -> close`
  一般 bug（錯誤）、test failure（測試失敗）、environment difference（環境差異）、CI failure（持續整合失敗）與普通 Git conflict（版本控制衝突）必須先自行排障，不得把使用者當成逐步主管。
- 只有以下四類情況允許停止並要求使用者介入：
  1. 必須由真人完成的 GUI（圖形介面）、UAC（使用者帳戶控制）或實體操作。
  2. 必須越過既定 construction boundary（施工邊界）。
  3. 將修改 formal locks（正式鎖）或涉及 External Action（外部行動）、交易、資金移動或帳戶權限。
  4. 已合理自行排障但仍客觀無法解除的真實 `BLOCKED`。
- 除上述四類之外，`READY_FOR_COMMIT`、中間測試完成、一般排障進度或「下一步是否繼續」不得成為打斷使用者的理由。

#### Agent division（代理分工）

- ChatGPT（一般對話）負責 research（研究）、evidence intake（證據輸入）、reasoning（推理）、problem definition（問題定義）、specification（規格）、necessity check（必要性檢核）、construction boundary（施工邊界）與 acceptance criteria（驗收條件）。
- Codex（程式施工代理）負責 repository work（版本庫工程）、程式修改、測試、除錯、regression（回歸）、Commit（提交）、Push（推送）、PR（合併請求）、Merge（合併）與 post-merge verification（合併後驗證）。
- Work（工作模式）負責 Windows 實機、PowerShell（命令列）、administrator elevation（系統管理員提升）、TWS（交易工作站）、Task Scheduler（工作排程器）、package / environment（套件／環境）、local files（本機檔案）、deployment（部署）與 actual-machine validation（實機驗證）。
- 能由 Work（工作模式）直接操作本機完成的 Windows 實機工程，不得退化成人工逐步貼 PowerShell（命令列），除非 Work（工作模式）不可用、額度耗盡或平台客觀阻塞。
- Manual Engineering Fallback（人工工程備援）只在 Work（工作模式）或 Codex（程式施工代理）真正不可用時啟用；啟用時應盡量提供一次性完整施工，而非把流程切成多輪人工搬運。

#### 禁止 Human Courier Mode（人肉快遞模式）

- 不得形成 `Work -> User -> ChatGPT -> User -> Work` 或 `Codex -> User -> ChatGPT -> User -> Codex` 的例行資訊搬運鏈。
- 只要代理有能力自行讀取、搜尋、執行、驗證或比較，就必須自己完成。
- 使用者不是 Agent（代理）的 Project Manager（專案經理）、秘書或人工 API（人工介面）。

#### Gate Necessity Rule（關卡必要性規則）

- 新增任何 gate（關卡）、attestation（證明）、manifest refresh（清單更新）、package rebuild（套件重建）或重複驗證前，必須先回答：
  「如果不做，會造成哪一個具體 correctness（正確性）、safety（安全）、evidence integrity（證據完整性）或 formal governance（正式治理）風險？」
- 若無法指出具體風險，該事項不得成為 blocking gate（阻塞關卡）；最多標記為 `WARNING` 或 `KNOWN_LIMITATION`。
- 「比較完整」、「比較好看」、「方便稽核」、「以防萬一」本身不是阻塞理由。

#### Verified Work Reuse（已驗證成果承接）

- 已取得 `PASS` 的驗證不得無理由重跑。
- 只有 code（程式碼）、relevant input（相關輸入）、environment（環境）或直接影響該能力的 dependency（相依項）發生實質變化，才重跑對應驗證。
- 不得因切換聊天室、代理、分支或施工階段而自動把既有有效 `PASS` 歸零。

#### Release-only Work（僅正式發布才做的工作）

- provenance refresh（來源追溯更新）、formal package reissue（正式套件重發）、manifest rebuild（清單重建）、額外 Review Pack（檢核包）與 Test Report（測試報告）只在 Formal Release（正式發布）、Migration（遷移）或確有必要的特殊隔離整合時執行。
- 一般 feature integration（功能整合）不得被上述 release ceremony（發布儀式）阻塞。

#### Human Lifetime Cost（人類生命時間成本）

- Human attention（人類注意力）與 user lifetime（使用者生命時間）是工程成本，不是免費資源。
- 能由機器自行多花運算時間而減少使用者操作、等待、搬運與重複確認時，預設讓機器承擔。
- process overhead（流程負擔）若不能降低實際風險或提升 North Star decision quality（北極星決策品質），即應刪除。

### 5. Local Git 身分、傳輸與成果承接｜Local Git Identity, Transport, and Transfer

#### Repo Root Lock（版本庫根目錄鎖）

- CRT_Master 唯一 Local Git（本機 Git）施工入口固定為：
  `C:\Users\maxwe\OneDrive\文件\GitHub\CRT_Master`
- Work / Codex（工作模式／程式施工代理）在任何 Git 動作前，必須先執行 `git rev-parse --show-toplevel`，並確認輸出與上述路徑完全相符；不一致即 `BLOCKED`，不得自行猜測 repo root（版本庫根目錄）或從父目錄繼續。

#### Git Transport Preflight（Git 傳輸前檢）

- 新工程開工前必須驗證 remote reachable（遠端可達）、credential helper available（憑證輔助程式可用）、使用者 Local Git 可承接最終 Push（推送），且 final Git write path（最終 Git 寫入路徑）已知。
- 不得做到 full regression（完整回歸）後，才發現施工環境無法 Push（推送）。

#### Commit Transferability（提交可轉移性）

- 若 Work / Codex（工作模式／程式施工代理）的施工環境與使用者 Local Git 不是同一個 repository object database（版本庫物件資料庫），不得將該環境的 commit SHA（提交雜湊）宣稱為「已在本機可 Push 的成果」。
- 施工前必須確認 commit / branch / worktree（提交／分支／工作樹）如何真正回傳至使用者 Local Git。

#### Patch Fallback（補丁備援）

- Patch（補丁）只在 Git 寫入失敗，或 commit / branch / worktree（提交／分支／工作樹）沒有真正落到使用者 Local Git 時使用。
- 一旦確認 commit / ref（提交／參照）不存在於使用者 Local Git，立即切換 Patch Recovery（補丁恢復）；不得反覆嘗試不存在的 commit / ref。

#### No Human Relay（禁止人肉快遞）

- 凡 Work / Codex 能自主完成的 repo 定位、Git 狀態檢查、isolated worktree（隔離工作樹）建立、Patch apply（補丁套用）、tests（測試）、regression（回歸）、Push（推送）與 PR（合併請求），不得拆成多輪要求使用者複製命令、執行、截圖、貼回，再取得下一條命令。
- 只有真正需要 human approval（人類批准）、GUI（圖形介面）手動互動、Formal lock（正式鎖）、stash（暫存修改）、elevated / destructive OS action（提升權限／破壞性系統動作），或代理已合理排障仍無法解除的 blocker（阻塞）才可停止。

#### Fail-Stop Output Discipline（失敗即停輸出紀律）

- 自動腳本任一步失敗後，不得繼續執行後續步驟或印出 `SUCCESS`。
- 互動式 PowerShell（命令列）診斷預設不得以 `exit 1` 關閉使用者整個視窗；必須保留視窗或落下完整 log（日誌），並清楚顯示 root cause（根因）。

#### Tool Division（工具分工）

- ChatGPT（一般對話）負責研究、證據、假說、判斷、規格、驗收條件與施工骨架；Codex（程式施工代理）負責 repository code changes（版本庫程式修改）、isolated worktree、tests、regression、Commit / Push / PR；Work（工作模式）負責 Windows 實機、PowerShell、本機檔案、Local Git、TWS、Task Scheduler（工作排程器）、deployment（部署）與實機驗證。
- Manual Engineering Fallback（人工工程備援）只在 Work / Codex 額度耗盡、平台阻擋或工具不可用時啟用，並採一次性完整施工；不得把它降格為日常流程。

#### ChatGPT GitHub App Boundary（ChatGPT GitHub 應用程式邊界）

- ChatGPT GitHub App 只用於 read / search / verify（讀取／搜尋／驗證）current `main`（目前主分支）；Branch / Commit / File write（分支／提交／檔案寫入）一律由 Local Git 完成。
- 若遇 `HTTP 403`，不得反覆重試，也不得視為 CRT 程式故障。

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
