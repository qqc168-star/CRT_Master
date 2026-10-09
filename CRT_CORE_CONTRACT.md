# CRT Core Contract

## North Star

CRT exists to improve capital decisions by answering five questions:

1. What BTC season are we in?
2. Is market weather improving or worsening?
3. What forces are dominant?
4. What role should each tracked asset play in the current regime?
5. Should capital BUY, SELL, HOLD, WAIT, or ROTATE?

Everything in CRT must serve at least one of these questions or protect the integrity of the answers.

## Role Boundary

### Automation — Evidence Kitchen / Sous-chef

Automation performs deterministic, repeatable work:

- collect decision-relevant data;
- validate source, schema, timestamp, freshness, and numeric sanity;
- normalize and calculate approved metrics;
- compare material 1D / 7D / 30D changes;
- detect meaningful changes, extremes, divergences, and conflicts;
- compress results into a CRT Evidence Pack;
- fail closed when critical evidence is missing, stale, invalid, or unverifiable.

Automation must not invent investment logic, silently alter approved formal models, infer open-ended causal narratives, assign final asset roles, issue autonomous trade decisions, or perform external actions.

### GPT — Chief Analyst / Chef

GPT performs high-level judgment:

- causal reasoning and multi-evidence synthesis;
- distinguish independent evidence from correlated signals;
- interpret leading, coincident, and lagging evidence;
- judge BTC season, market weather, and dominant forces;
- determine asset roles under the current regime;
- propose capital strategy with evidence, uncertainty, invalidation, and what would change the view.

GPT should not repeatedly perform large deterministic calculations that belong in automation and must not silently modify approved formal models, weights, thresholds, or governance locks.

### User — Capital Decision Authority

The user defines objectives and risk constraints, approves formal model changes, makes final BUY / SELL / HOLD / WAIT / ROTATE decisions, and alone authorizes real-world execution outside CRT.

## Core Workflow

`World -> Automation -> CRT Evidence Pack -> GPT Analysis -> User Decision`

Automation prepares evidence. GPT creates judgment. Human commits capital.

### Decision Closure Lock

CRT terminates in capital decision support, not Radar / Evidence alone. The complete North Star chain is:

`World -> Radar -> Evidence -> Causal Analysis -> Season / Regime -> Asset / Issuer Health -> Valuation -> Capital Posture -> Portfolio Translation -> Investment Recommendation -> User Capital Decision`

Radar is the sensing / input layer, not the final CRT output. When evidence permits, complete decision support must continue to `BUY / SELL / HOLD / WAIT / ROTATE` recommendations. Where applicable and supported, include:

- exact price / condition and quantity / capital amount;
- attack line, first defense, invalidation, and harvest;
- supporting evidence, contradiction / uncertainty, and what changes the view.

Unsupported claims remain subject to the claim-scoped fail-closed rule; this closure requirement never authorizes invented prices, quantities, or evidence. User remains Capital Decision Authority. Recommendations grant no machine execution authority and do not change Production approval or External Action Authority.

### Source Decision-Linkage Lock

No source work without decision linkage.

Before adding or repairing any scraper, API integration, source adapter, anti-bot workaround, or redirect / cookie / transport workaround, identify the exact CRT decision or existing downstream contract it improves.

A primary / official source does not automatically become a daily runtime dependency merely because it is more authoritative. When a mature integrated source sufficiently supports the required decision claim, weigh reliability, provenance, freshness, maintenance burden, and decision value. This principle does not override existing formal source locks or permit lower-precision evidence to replace a blocked formal claim.

The comprehensive Decision-Purpose / Data-Purity Audit is deferred until the complete CRT decision chain works end to end; this lock does not authorize a general source cleanup.

### Engineering Dispatch Discipline

Architecture before construction.

N.S. Central defines objective, architecture, source selection, boundaries, and acceptance criteria before dispatch. CRT MASTER Work implements the defined specification; it must not independently redo architecture selection.

`N.S. Central decision -> one independently closable organ -> Construction -> Validation -> Seal & PR -> N.S. architecture review -> Merge -> reread current main -> next dispatch`

- Use this single continuing CRT MASTER engineering chat and execute one independently closable organ at a time. Do not create another Work chat on task switches, parallel Work chats competing for main, or advance Work A / B / C / D queues.
- One chat does not mean one permanent branch / worktree. After each independently completed and merged task, reread current GitHub main as Engineering SSOT and, as needed, create a clean isolated worktree from that main for the next task. Never touch existing stash.
- Stop construction and report to N.S. when architecture selection, a formal lock, source selection, cross-module conflict, or a defective specification requires a decision. Do not invent a solution and continue construction.
- Every task follows Construction -> Validation -> Seal & PR. Construction must not commit or push. Validation includes targeted tests and full regression, followed by git status and git diff --check; only after all pass may add, commit, push, and PR proceed.
- After PR creation, return to N.S. for architecture review. Central does not rerun completed full regression without a new concrete reason. Merge still requires authorization; the next dispatch is decided only after N.S. rereads the latest current main.

#### Validation Responsibility Lock

Work owns construction validation. Before Seal & PR, CRT MASTER Work must complete targeted tests + full regression, compile / static checks required by the existing repository workflow, git status, and git diff --check. Tests must not be omitted to save quota or time.

N.S. owns architecture review. Central reviews the PR diff, architecture compliance, formal-lock preservation, Work test evidence, and verifiable CI / GitHub results. It must not routinely rerun Work's completed full regression merely for repeated confirmation without a concrete reason.

Rerun is risk-triggered, not ritual. N.S. Central or Work must rerun appropriate tests when any of these triggers occurs:

- a new PR commit after the original validation;
- a changed base SHA;
- merge conflict / rebase;
- missing or unverifiable test evidence;
- CI results inconsistent with Work's report;
- architecture review identifies an important risk not covered by existing tests;
- changes affect a previously untested module;
- test configuration / dependency changes;
- another concrete, explainable technical reason.

Rerun only tests sufficient to verify the identified risk; rerun full regression when the risk may affect the whole repository. This risk-scoped rerun rule does not waive Work's required construction validation before Seal & PR.

Saving quota must remove duplication, not verification. Never skip targeted tests, full regression, or diff checks to save Work quota, and never substitute N.S. architecture review for construction tests. Do not make Work testing -> unjustified Central retesting -> next Work retesting a fixed repetitive process.

#### N.S. Work Allocation & Model Budget Discipline（總工程師工作分配與模型額度紀律）

**Core Principle（核心原則）：總工程師先做滿、施工隊精準施工、參謀長只處理高價值挑戰。**

1. **N.S. Central（總工程師）最大化前置作業。** 在交辦之前，優先自行完成主分支核對、資料查證、計算、分析、問題定位、架構決策、反證設計、修改邊界與驗收條件。能自行解決的工作，不應轉交高額度模型重複探索。
2. **CRT MASTER Work（施工隊）僅承接必要工程。** 主要負責本機程式及文件修改、隔離工作樹、測試、提交、推送與 PR（合併請求）。施工隊不得無故重做 N.S. 已完成的架構選擇；若發現規格錯誤或重大風險，停止並交回 N.S. 裁決。
3. **模型強度依工作難度決定。** N.S. 每次交辦都必須明確指定強度與理由。簡單文件或局部修改優先 Medium（中等強度）；一般跨模組整合使用 High（高強度）；重大架構衝突、複雜高風險工程才使用 Ultra（最高強度）。模型名稱及實際檔位依當時可用能力選擇。
4. **參謀長按需召喚，召喚時使用最高可用強度。** 專責重要研究、競爭假說、因果反證、策略挑戰及必要的獨立架構審視。參謀長無正式架構修改、工程寫入或資本執行權限；研究成果交 N.S. 裁決。
5. **節省模型額度不等於削減驗證。** 施工隊仍須完成必要的針對性測試、完整回歸、靜態檢查與 Git 差異檢查。N.S. 優先複用可驗證測試成果，沒有具體風險不得要求無意義重測。
6. **跨聊天室接力必須繼承分工。** 新任總工程師首先讀取當時 current main（目前主分支），核對最新工程及待辦事項，再依本準則決定由自己、施工隊或參謀長處理。不得以聊天記憶取代主分支事實。
7. **治理邊界維持。** 不變更正式六層權重、燈號閾值、mNAV（資產淨值倍數）語義、正式季節、生產批准、外部行動權限及使用者最終資本決策權。本準則不新增官僚式工程程序。

### Project Operating Rooms Lock

第一顆比特幣｜CRT has exactly three permanent main rooms:

1. **礦場淘金｜Research Mine** collects external research, examines predecessor viewpoints, challenges CRT hypotheses, discovers causal mechanisms, and finds incremental decision value. Its output is research findings / candidate insights. It has no architecture authority: it must not modify CRT architecture, decide formal source selection, change formal locks, or independently establish Engineering SSOT. Valuable research returns to N.S. Central to decide whether it should be engineered.
2. **總工程師｜N.S. Central** is the architecture / integration authority. It reads current GitHub main, understands research and engineering state, defines objective, architecture selection, source selection, module integration, engineering boundaries, and acceptance criteria, and owns Work dispatch and PR architecture review. After Merge it rereads current main and selects the next organ actually blocking the CRT decision chain. CRT MASTER Work must not replace Central in these decisions.
3. **雷達城｜CRT Decision Operations** operates CRT against real markets through `Radar Truth -> Evidence -> Causal Analysis -> Season / Regime -> Asset / Issuer Health -> Valuation -> Capital Posture -> Portfolio Translation -> Investment Recommendation -> User Capital Decision`. Radar is a sensing / input layer, never the terminal output. When evidence permits, recommendations must reach `BUY / SELL / HOLD / WAIT / ROTATE`, with the applicable evidence-supported prices / conditions, quantities / capital amounts, attack line, first defense, invalidation, harvest, supporting evidence, contradiction / uncertainty, and what changes the view specified by Decision Closure Lock. User remains the sole Capital Decision Authority.

CRT MASTER Work is not a fourth main room. It is the single continuing engineering workspace, with this permanent construction chain:

`N.S. Central -> CRT MASTER Work -> Construction -> Validation -> Seal & PR -> N.S. architecture review -> Merge -> reread current main -> next N.S. dispatch`

Continue using the same Work chat. After an independent task is completed and merged, the next task must use the latest current main and, as needed, a new clean isolated worktree. Existing stash remains untouched.

These locks do not change the six-layer weights, light thresholds, mNAV semantics, formal Season Router semantics, Production approval, External Action Authority, or machine execution permissions. They introduce no Phase / Wave / Dashboard / Work Order framework.

## Fail-Closed Rule

Missing, stale, invalid, or unverifiable critical evidence must produce `BLOCKED` rather than a fabricated value or false certainty.

Evidence is not a decision. A score is not a season by itself. A historical PASS does not make future evidence valid.

## Evidence Precision Constitution

Precision follows the claim and decision use; the claim must not be forced to match the maximum precision available from a source.

CRT uses three evidence precision levels:

### Directional / Research Evidence

Use for trend, direction, acceleration, breadth, structural context, and hypothesis formation.

Directional evidence may use partial but real coverage, a stable tracked basket, mature processed research sources, and date- or period-level timestamps when those are sufficient for the claim.

It does not require complete-universe coverage, a formal total, or millisecond timestamp precision unless the claim itself depends on them.

### Deterministic / Comparable Evidence

Use for reproducible 1D / 7D / 30D comparisons and other deterministic change calculations.

It requires stable metric semantics, comparable scope or basket, sufficient identity, explicit as-of semantics, and reproducible calculation inputs.

Partial universe coverage is acceptable when the comparison scope is explicit and materially comparable across observations.

### Formal / Action-Critical Evidence

Use for exact total-market claims, formal model inputs, approved thresholds, gates, market-dependent formula locks, Production promotion, or external actions.

These claims require the coverage, identity, timing precision, prerequisites, and approvals necessary for that exact claim.

### Claim-Scoped Fail-Closed Rule

`BLOCKED` is claim-scoped, metric-scoped, or calculation-scoped. It must not automatically invalidate independent evidence that remains real, relevant, and usable for a narrower claim.

A missing or invalid total does not invalidate verified constituents. Incomplete universe coverage does not invalidate a clearly labeled tracked-basket trend. Date-level source timing does not require invention of a false millisecond timestamp.

When evidence cannot support the strongest intended claim, CRT must first reduce claim scope or precision and preserve the valid evidence. It should discard the evidence only when the remaining evidence cannot support a decision-relevant claim at any appropriate precision level.

Partial real evidence must remain visible with explicit scope, provenance, as-of semantics, and limitations.

Fail-closed still forbids fabricated values, zero-fill, guessed identities, silent stale reuse, fake timestamps, or promotion of lower-precision evidence into a stronger claim than it supports.

GPT may use appropriately labeled lower-precision evidence for qualitative judgment, but must state uncertainty and must not silently promote it into a formal exact claim.

## Governance Boundary

- Production remains `NOT_APPROVED` unless explicitly changed by later formal approval.
- External Action Authority remains `NONE` unless explicitly changed by later formal approval.
- No trading, account access, or fund movement is authorized by this contract.
- Existing approved formal models, weights, thresholds, mNAV semantics, and other formal locks are not changed by this contract.
- Existing stash state must not be applied, popped, dropped, or rewritten by this contract.

## Knowledge Survival Rule

No essential CRT knowledge may depend on one chat session.

`Conversation -> Finding -> Verification -> User Approval -> Contract / Code / Test -> Git commit`

Unapproved discussion may disappear. Approved knowledge that must survive context loss must be promoted into the repository.

## Finding Retention Filter

Every newly discovered viewpoint, indicator, rule, module, or proposed permanent CRT knowledge item must be re-examined through all three questions before promotion:

1. **Necessity** - If this finding disappeared, would CRT materially lose decision quality, evidence integrity, or the ability to answer a North Star question?
2. **Purpose** - What exact CRT decision, evidence task, or governance problem does the finding serve?
3. **Specificity** - Does the finding address a demonstrated CRT gap directly, rather than duplicate an existing capability or expand scope without a concrete need?

Failure on any one question means the finding must not be promoted into permanent CRT structure. It may remain as Research / Observation when it still has evidentiary value, or be discarded when it does not.

Passing all three questions grants only eligibility for verification. It does not automatically create a formal metric, score, threshold, layer, model, production rule, or trading authority.

## Lean Rule

Before adding a file, module, metric, process, or automation, ask:

> If this disappeared, would CRT materially lose its ability to judge season, weather, dominant forces, asset roles, capital actions, or the trustworthiness of evidence supporting them?

If not, default to not adding it.
