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
4. Read `radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md` for preserved formal locks.
5. Inspect current executable code and tests before claiming a capability exists.
6. Read the single `CRT Active Baton` working bookmark if one exists.
7. Report: North Star, role boundaries, governance locks, verified capabilities, BLOCKED gaps, current objective, and next effective action.

Never reconstruct missing formal implementation from old chats or memory. If the formal basis is absent, report `BLOCKED`.

## 永久使用者語言規則｜User-facing Language Rule（對使用者語言規則）

- CRT（第一顆比特幣決策研究體系）對使用者輸出中，每次出現 English term or acronym（英文術語或縮寫）時，都必須立即附上繁體中文註解。
- `Code`（程式碼）、`commands`（命令）、`paths`（路徑）、`identifiers`（識別碼）、`field names`（欄位名稱）與其他 machine-readable literals（機器可讀原始字串）必須保持原樣；中文說明放在原始字串外。
- 新聊天室必須從 current `main`（目前主分支）恢復此規則，不得要求使用者重新說明。

## 工程工作慣性｜Engineering Workflow Habit（工程流程習慣）

- 保留 pre-construction plan（施工前規劃）與 complete regression testing（完整回歸測試）；先規劃，再施工，施工後完整驗證。
- GitHub（程式碼託管平台）正常可寫時，以 `Branch / Commit / PR`（分支／提交／合併請求）作為正常 engineering memory（工程記憶）。
- 不得把 `Review Pack / ZIP / Patch / Test Report`（檢核包／壓縮檔／補丁／測試報告）變成每刀固定流程。
- 只有 GitHub write access（GitHub 寫入權限）被阻擋，例如 `HTTP 403`（拒絕寫入）時，才以 `Patch`（補丁）搭配簡短 `Test Summary`（測試摘要）作備援交付。
- `Formal Release`（正式發布）、`Migration`（遷移）或 special isolated integration（特殊隔離整合）時，才依需要增加打包。
- `Simplicity first`（簡單優先）；process overhead（流程負擔）不得自行長成新的 gate（關卡）。

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
