# CRT Portfolio Allocation Context V0.1（CRT 投資組合配置脈絡 V0.1）

Engineering SSOT（工程唯一真實來源）施工基準：`main@ffb308ae301fccabb0067a88147a68e48bef88d7`。

## 定位

本增量把既有 CRT（第一顆比特幣決策研究體系）器官接成同一條資本脈絡：

`Evidence -> Season / Weather -> Next-season destination -> Treasury / Common Equity Health -> Valuation -> Portfolio Allocation -> Fixed-income carrier -> Commander -> GPT / N.S. judgment -> User decision`

它不建立第二套 Treasury（財庫）引擎、mNAV（資產淨值倍數）引擎、Issuer Fact Store（發行人事實庫）、Season Router（季節路由器）或 BUY/SELL engine（買賣引擎）。

## 配置語義

`Total Portfolio = Cash Pool + Invested Capital`

`Invested Capital = Fixed Income + Growth`

- Cash（現金）用 total-portfolio percentage（總投資組合百分比）。
- Fixed Income / Growth（固定收益／成長）用 invested-capital bucket percentage（已投入資本桶內百分比）。
- MSTR / ASST 用 growth-bucket percentage（成長桶內百分比）。

四季目的地：

| Destination（到站） | Cash | Fixed / Growth | MSTR / ASST within Growth |
|---|---:|---:|---:|
| Winter（冬季） | 12–15% | 80 / 20 | 80 / 20 |
| Spring（春季） | 8–10% | 70 / 30 | 65 / 35 |
| Summer（夏季） | 5–7% | 60 / 40 | 55 / 45 |
| Autumn（秋季） | 10–15% | 75 / 25 | 75 / 25 |

Severe stress（嚴重壓力）可研究到 20% Cash 上限。Summer（夏季）55/45 Fixed/Growth 只在明確標示 `extreme_summer_research_candidate` 時成立，不是正常基準。

Spring（春季）Growth（成長桶）可按既有研究脈絡使用 Early 70/30、Center 65/35、Mature 60/40。

## Common Equity Health（普通股健康）

健康與估值永久分開。Health（健康）回答「公司有沒有創造每股價值」，Valuation（估值）回答「市場價格付多少」。

本增量重用 Treasury Company CT（財庫公司斷層掃描）與 Treasury Valuation Context（財庫估值脈絡）的已驗真事實，不新增第二份發行人資料庫。核心觀測：

- `net_residual_value_per_diluted_share`
- `btc_per_diluted_share`
- `btc_per_diluted_share_change_pct`
- `diluted_share_change`
- `senior_claim_change_usd`
- `annual_carry_change_usd`
- `liquidity_change_usd`
- Cash / Reserve Coverage（現金／準備金覆蓋）
- Capital Conversion Evidence（資本轉換證據）

Residual（剩餘價值）只在 BTC 價格、可用流動性、其他已驗真流動資產、Senior Claims（優先索取權）與 coherent diluted shares（同口徑稀釋股數）完整時才計算；未知不得補零。上游還必須提供 `capital_structure_coherence_state = VALIDATED` 與非空 `capital_structure_scenario_ref`，明確證明本次 residual scenario（剩餘價值情境）沒有把 convertible（可轉債）同時當成完整債務與完整稀釋股數雙算；未閉合時只封鎖 residual claim（剩餘價值主張）。

Health direction（健康方向）只使用 `IMPROVING / STABLE / DETERIORATING / BLOCKED`。不新增分數、燈號或第七層。

一般 relative-health tilt（相對健康傾斜）上限為 5 percentage points（百分點）；只有明確 persistent structural difference（持續性結構差異）才允許 10 percentage points。任何健康傾斜都須先取得 Valuation clearance（估值放行）；`BRAKE` 或缺乏放行不得因健康改善而自動加碼。

## 雙釵長短週期分工

Long-cycle Roll（長週期換釵）維持既有心智模型與正式研究規則，不由本增量重寫：

`FULL_PRESERVATION_PASS + ROLL_CAPITAL_GROWTH >= 1%`

Short-cycle Side Job（短週期兼差）是獨立時間路由：

`SATA -> STRC D-1 entitlement window -> STRC D -> SATA`

核心式：

`NetSideJobEdge = STRC distribution + exit - entry - foregone SATA carry - trading friction - tax friction`

D 日最低撤退價：

`ExitFloor = EntryPrice - STRC distribution + foregone SATA carry + trading friction + tax friction + required edge`

D-1（除息前一日）machine（機器）只負責計算 `ExitFloor` 與保存可驗證輸入，不自行預測 D 日價格。是否值得進入本輪兼差由 N.S./GPT（分析主廚）依當下市場與歷史證據給 `analyst_entry_gate_state = PASS / FAIL`；缺少該判斷時為 `BLOCKED`。

狀態只有：

- `EXECUTE`
- `SKIP`
- `EXIT_PENDING`
- `BLOCKED`

Existing STRC inventory（既有 STRC 庫存）與 Side-job Capital（兼差資本）分帳。輸出分列 `legacy_strc_inventory_shares`、`side_job_capital_usd`／`side_job_confirmed_strc_shares` 與 `capital_scope_state`；若兼差資本範圍尚未確認，per-share edge（每股優勢）仍可研究，但不得把既有 STRC 庫存冒充本輪快閃兵。兼差超過 max-hold boundary（最長持有邊界）只交回 long-cycle review（長週期檢視），不得偷長成新的停損／交易引擎。

## Season（季節）與提前部署

本模組不產生正式 Season（季節）。只接受：

- 已可用的 Formal Season（正式季節）；或
- `LABELED_ANALYST_HYPOTHESIS` 且有 independent evidence（相對獨立證據）的研究假說。

Formal Season（正式季節）`BLOCKED` 時不得偷填 Winter（冬季）。

Allocation destination（配置到站）可以領先 current posture（目前姿態），因此支援：

- Late Winter -> Spring positioning
- Mature Spring -> Summer positioning
- Late Summer -> Autumn harvest
- Late Autumn -> Winter defense

這只表示資本目的地，不是交易觸發器。

## Evidence / GPT / Commander（證據／GPT／統帥）接線

Evidence Pack（證據包）本地保存完整 `common_equity_health` 與 `portfolio_allocation_context`。

GPT bridge（GPT 橋）只傳送 compact projection（精簡投影），避免原始私人帳戶資料與重複 Treasury 證據進入 bridge（橋接），並維持既有 16 KiB 上限。

`asset_strategy_delta` 在沒有新 context（脈絡）時保持舊輸出；只有 context 可用時才：

- 將 SATA 表達為 Fixed Income carrier（固定收益平時載體）；
- 將 STRC 表達為 income / side-job option（收益／兼差選項）；
- 用真實 Common Equity Health + Valuation（普通股健康＋估值）取代 MSTR / ASST 的永久假阻塞。

任何 machine output（機器輸出）仍為 `action_output = NONE`；具體攻擊線、防線、收割線、股數與 Capital Action（資本行動）仍屬 Commander + N.S.（統帥＋分析主廚）判斷，User（使用者）保有最終決策權。

## Governance locks（治理鎖）

保持不變：

- 六層權重 `20 / 20 / 17 / 25 / 13 / 5`
- 燈號 `-60 / -35 / 35 / 60`
- 未限定 `mNAV` = Diluted Equity mNAV（稀釋後股權資產淨值倍數）
- Production（正式生產）`NOT_APPROVED`
- External Action Authority（外部行動權限）`NONE`
- Capital Decision Authority（資本決策權限）`USER_ONLY`
- Wake `90 / 95` policy（喚醒政策）
- Transport（傳輸）
- IBKR execution（券商執行）
- 既有 stash（暫存修改）

本 Work（工作）不建立 Active Baton（現行接力棒）第 9 項，也不啟動第 8 項。
