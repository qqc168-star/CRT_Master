# CRT_REFLEXIVITY_RECIPE_SPEC_V0.1

```yaml
artifact_status: N.S._REVIEW_APPROVED
implementation_status: IMPLEMENTED_DELTA_READY_FOR_INTEGRATION
execution_state: N.S._GO_RECEIVED
artifact_mode: REPOSITORY_SPEC
overlay_type: NON_WEIGHTED_EVIDENCE_OVERLAY
production: NOT_APPROVED
external_action_authority: NONE
implementation_base_sha: d2905989f1b0957571fbc3b4a6fbf5ffcd7a9c1a
```

## 0. Scope and governance lock

本規格保留 `CRT-ISSUER-001` 的核心思想，並依 N.S. 重新定位為：

> `CRT-ISSUER-001 = NON-WEIGHTED EVIDENCE OVERLAY`

它只回答一條可追溯的回饋迴路：

> 公司做了什麼？
> → 市場如何反應？
> → 反應是否改變公司的下一步資本工具與行動空間？
> → 公司下一步若再行動，市場反應機制可能如何改變？

治理邊界：

- 不新增第七層。
- 不增加正式分數。
- 不改六層 weights。
- 不改 thresholds。
- 不改 BTC Season 邏輯。
- 不直接輸出 BUY／SELL。
- 不把相關性冒充因果。
- Automation／程式負責蒐集、驗證、正規化、確定性計算、事件整理與 Evidence Pack。
- GPT 負責因果推理、反身性解讀、市場反應判斷、資產角色與策略。
- User 是最終資本決策者。
- `External Action Authority = NONE`。

工程基準：GitHub `qqc168-star/CRT_Master` current `main`。本規格服從 `README.md`、`CRT_CORE_CONTRACT.md` 與 `CRT_EVIDENCE_PACK_CONTRACT.md`；若未來 current `main` 與本規格衝突，必須停止實作並重新審閱，不得默認覆蓋 SSOT。

---

## 1. KEEP

| 保留洞見 | N.S. 中的正式位置 |
|---|---|
| 公司行動 → 市場反應 → 公司資本空間改變 → 下一輪公司行動 | 反身性核心迴路 |
| execution、disclosure、reaction 是三座不同的時鐘 | 強制事件時間語義 |
| 回購很多不必然是利多；可能代表自然需求不足 | GPT 判斷問題 |
| 公司減少干預後價格仍強，才是較可信的市場接棒 | GPT 判斷問題 |
| 高干預、弱價格反應可能表示供給牆沉重 | GPT 判斷問題 |
| 股價、折溢價會反過來改變 ATM、回購、發債、BTC 買賣空間 | 資本工具反身性 |
| 公司可能由買方轉為減速者、供給者或融資者 | issuer-role transition |
| 回購額度、現金、ATM 容量、實際執行是四件不同的事 | 客觀事實分離 |
| 回購金額不等於消滅同額折價；其效果仰賴剩餘證券重新定價 | 算術與因果防火牆 |
| 相同行動的市場反應可能逐次增強或衰減 | 跨事件 GPT 比較 |
| raw event 不因後續修訂而刪除，須以 supersession 串接 | 事件溯源治理 |

---

## 2. HISTORICAL_ONLY

下列內容只保留為 STRC 案例、未來 fixture 或研究假說，不升格為通用參數：

- 2026 年 6 月 29 日、7 月 27 日、8 月 3 日的 STRC 事件與市場反應。
- 每週一美東 `08:00:14–08:00:17` 的 8-K 節奏及 8 月 10 日預測。
- `90／94／95／100` 美元區間、9 月 8 日驗收日。
- 公司成交占比 `8%／15%` 的舊影子門檻。
- 本週約回購 60 萬股、`2.5 億／4 億／2.438 億` 的假想資金配置。
- 事件日約 `1.39×` 成交量與「每投入多少美元推升多少價格」的舊比較。
- 173.9 股、80 股核心倉、各段賣價，以及 `77.91／78.36` 成本衝突。
- STRC 特定法律、股息與回購條款；若再使用，必須重新確認 `source-as-of` 與 supersession。

這些不是丟棄，而是被安放回它們應在的抽屜：案例，不是憲法。

---

## 3. REWRITE

| 舊方法 | N.S. 改寫 |
|---|---|
| `CRT-ISSUER-001 Gate` | 改為 Evidence Overlay，不控制六層分數與燈號 |
| 市場接棒矩陣直接給「最佳／警訊」 | Automation 只交原料；GPT 才能判斷 |
| 回購股數 ÷ 總成交量＝公司買盤占比 | 僅在證券、窗口、渠道、成交量範圍一致時成立 |
| `1 − 公司占比`＝市場自主買盤 | 禁止；一般公開成交資料無法識別全部買方身份 |
| 8-K 公告日反應代表上一週回購效果 | 拆成 execution、disclosure、reaction 三個窗口 |
| 回購金額／股價變化＝回購效率 | 禁止因果命名；只能記錄同窗並存的客觀結果 |
| 固定週一秒級公告時間 | 保存為觀察到的歷史 cadence，不硬編碼 |
| 假想操盤經理資金配置 | 留給 GPT 情境推演，不進 Evidence Pack |
| 空陣列、缺欄位、零值都視為沒有事件 | 改為 fail-closed absence semantics |
| 新文件直接覆蓋舊資料 | 舊事件不刪除，以 supersession 狀態決定能否參與計算 |

---

## 4. 二廚必備原料

### 4.1 身份

- 穩定 `issuer_id` 與識別方案，例如 CIK／LEI。
- `security_id`、ticker、class、security type、交易所、幣別。
- issuer-security 關係及其有效期間。
- ticker 不得單獨充當永久身份。

### 4.2 來源與時間

- `source_id`、文件 ID／SEC accession、文件種類、來源 URL。
- `source_as_of_ms`、`published_at_ms`、`retrieved_at_ms`。
- evidence hash、registry hash、quality state。
- 原始文件、修訂文件及 supersession 關係。
- 時區、交易日曆、時間精度。

### 4.3 公司事實與事件

- 回購股數、金額、均價、渠道及執行窗口。
- 發行股數、ATM 使用量、總／淨募集金額、program identity。
- BTC 買入／出售數量、價格、金額與期間。
- 現金、美元儲備、BTC 持有量。
- basic／diluted／class-specific 股數及明確語義。
- 回購授權、已使用量、剩餘量、涵蓋證券。
- 融資成本、股息／distribution 條款、清算優先權。
- 管理層正式陳述可記作 `reported_policy_statement`，但不得被二廚翻譯成「真實意圖」。

### 4.4 市場原料

- 調整後與未調整 OHLC、成交量、交易時段。
- consolidated 或單一交易所成交量範圍。
- BTC 與核准指數的同步價格資料。
- corporate-action adjustment 狀態。
- 完整 execution、disclosure、reaction window coverage。

### 4.5 三個 observation windows

三者必須分開記錄，不得混用：

| Window | 定義 | 允許回答 |
|---|---|---|
| `execution_window` | 公司實際執行行動的時間範圍 | 公司在何時、以何種渠道、執行多少 |
| `disclosure_window` | 資訊首次合法公開並可被市場取得的時間範圍 | 市場從何時可能知道該事件 |
| `reaction_window` | 經核准規格定義、用於觀察揭露後反應的時間範圍 | 價格、成交量、波動與相對表現如何改變 |

若 execution 僅有週期總量，不得把它拆成虛構的逐日買盤；若 disclosure timestamp 不確定，不得自行選擇最有利的市場價格作為起點。

---

## 5. DETERMINISTIC CALCULATIONS

以下 `FORMULA_READY` 只代表公式與必要輸入已明確，不代表 current `main` 已實作。凡公式、來源、證券身份、計算口徑或時間窗未正式鎖定，輸出 `BLOCKED`，不得自行發明預設值。

| ID | 公式 | 必要條件 |
|---|---|---|
| `REPURCHASE_AVG_PRICE` | `eligible_cash_consideration / repurchased_shares` | 同事件、同幣別、股數大於零 |
| `OPEN_MARKET_PARTICIPATION` | `verified_open_market_repurchased_shares / comparable_consolidated_volume` | 同證券、同 execution window、公開市場渠道已確認 |
| `REPURCHASE_SHARE_RATIO` | `repurchased_class_shares / pre_event_class_basic_shares` | class 與 basic 語義一致 |
| `GROSS_ISSUANCE_RATIO` | `gross_issued_class_shares / pre_event_class_basic_shares` | 不得以淨股數變化代替 gross issuance |
| `NET_SHARE_COUNT_CHANGE` | `(post_basic_shares − pre_basic_shares) / pre_basic_shares` | 兩端使用相同股數語義 |
| `REMAINING_AUTHORIZATION` | `active_authorization − cumulative_eligible_spend` | authorization ID、涵蓋證券及 supersession 均明確 |
| `REMAINING_ATM_CAPACITY` | `active_program_capacity − cumulative_program_usage` | 容量與使用量必須同單位、同 program |
| `BTC_NET_FLOW` | `BTC_bought − BTC_sold` | 完全相同期間 |
| `LIQUIDATION_PREFERENCE_RETIRED` | `retired_shares × liquidation_preference_per_share` | 條款仍有效 |
| `DISTRIBUTION_RUN_RATE_REMOVED` | `retired_shares × current_annual_distribution_per_share` | 必須標記為當期 run-rate，不冒充永久節省 |
| `FIXED_WINDOW_RETURN` | `P_adj,end / P_adj,start − 1` | `window_spec_id` 與價格來源正式鎖定 |
| `BTC_EXCESS_RETURN` | `security_return − BTC_return` | 同窗口、同時間基準；不得稱為 abnormal return |
| `VOLUME_MULTIPLE` | `event_window_ADV / locked_baseline_ADV` | baseline、交易日數與市場範圍正式鎖定 |

### 5.1 預設 BLOCKED 的計算

- Event return、volume multiple、realized volatility、延續／回吐比例：在正式事件窗口與市場資料 source lock 完成前，一律 `BLOCKED`。
- 公司公開市場參與率：若文件混合公開市場、鉅額或私下交易，一律 `BLOCKED`。
- 市場自主買盤比例：除非有正式 buyer-identity 資料，一律 `BLOCKED`。
- 「每一美元回購造成多少漲幅」：缺少反事實與因果識別，禁止生成。

---

## 6. GPT REFLEXIVITY JUDGMENTS

下列判斷必須留給 GPT 主廚，不得由 deterministic rule 直接變成投資結論：

- 公司是在托底、吸收折價，還是在追價？
- 價格強勢有多少可能來自公司干預，有多少來自外部需求？
- 公司停止或降低買盤後，價格與成交是否仍能維持？
- 同類公司行動的邊際市場反應正在增強、鈍化還是反轉？
- 回購節省的融資成本，是否值得犧牲現金、BTC 或未來資本彈性？
- 股價上升是否重新打開 ATM、發債或 BTC 購買能力？
- 折價／溢價是否改變下一個最合理的資本工具？
- 公司是否由買方轉成減速者、供給者或融資者？
- 公告反應是否被同期 BTC、指數、宏觀事件或公司新一輪操作混淆？
- 哪些替代解釋仍成立？什麼新證據會推翻目前看法？

每項 GPT 判斷至少應附：

```yaml
evidence_refs: []
alternative_explanations: []
uncertainty: <explicit assessment>
invalidation: <what evidence would falsify the judgment>
next_observable: <next verifiable event or fact>
```

不得由單一 deterministic metric 自動轉成：

- `reflexivity_score`
- asset role
- capital strategy
- BUY／SELL
- 第七層或新權重

---

## 7. BLOCKERS

| Blocker code | 觸發條件 |
|---|---|
| `ISSUER_IDENTITY_UNRESOLVED` | issuer 無法唯一識別 |
| `SECURITY_IDENTITY_UNRESOLVED` | class／ticker／證券身份不確定 |
| `SOURCE_AS_OF_UNKNOWN` | 文件或數據的有效時間不明 |
| `SUPERSESSION_UNRESOLVED` | 新舊文件衝突，無法判斷現行版本 |
| `EXECUTION_DISCLOSURE_MIXED` | 執行期與揭露期被混作同一窗口 |
| `EXECUTION_WINDOW_INCOMPLETE` | 只知週期總量，卻試圖做日內或逐日分析 |
| `DISCLOSURE_TIMESTAMP_UNKNOWN` | 無法確定市場何時真正取得資訊 |
| `REACTION_WINDOW_INCOMPLETE` | 反應窗口尚未完成或資料缺口存在 |
| `SHARE_COUNT_BASIS_MISMATCH` | basic、diluted、class-specific 混用 |
| `ACTION_CHANNEL_UNKNOWN` | 公開市場、block、私下交易未分離 |
| `MARKET_VOLUME_SCOPE_MISMATCH` | 公司交易與市場成交量範圍不一致 |
| `PRICE_OR_VOLUME_UNVERIFIABLE` | 缺少可驗證市場資料 |
| `CORPORATE_ACTION_ADJUSTMENT_UNKNOWN` | 價格序列是否調整不明 |
| `BENCHMARK_WINDOW_MISMATCH` | 證券與 BTC／指數時間窗不一致 |
| `OVERLAPPING_MATERIAL_EVENTS` | 同期存在其他可能主導價格的事件 |
| `WINDOW_SPEC_NOT_APPROVED` | observation window 尚未正式鎖定 |
| `VERIFIED_ZERO_NOT_ESTABLISHED` | 無法證明公司在該窗口確實零行動 |
| `AUTHORIZATION_SCOPE_UNKNOWN` | 額度是否共用、涵蓋哪些證券不明 |

### 7.1 缺值與空集合語義

- 缺欄位或 `null`＝未知，不是零。
- `0` 只有在來源明確報告零值，且窗口與 coverage 完整時才有效。
- `[]` 只有在 `coverage_state=COMPLETE`、scope 明確且 `empty_reason=VERIFIED_NO_MATCH` 時，才能表示「驗證後沒有事件」。
- superseded 記錄不刪除，但不得進入 active calculation。
- Reflexivity blocker 預設只阻擋 Overlay 或特定 asset judgment，不自動污染六層 BTC pack state。
- blocker 缺欄位或 blocker array 為空，不得被解讀為「已驗證無阻礙」。

---

## 8. 最小 Evidence Pack contract delta

current `main` 在 base `d2905989f1b0957571fbc3b4a6fbf5ffcd7a9c1a` 已正式具有 `CRT_EVIDENCE_PACK_V0.2`、`asset_facts`、`decision_relevant_events`、`blockers` 與 top-level `action_output = "NONE"`。因此 Freeze 版「再升 V0.2、再新增四個 top-level section」的提案已被取代，不得重複實作。

四個 reflexivity input section 保留為 validation/calculation 模組的輸入語義，但輸出映射到既有 generic contract：

| Reflexivity input | Evidence Pack V0.2 output |
|---|---|
| `issuer_facts` | `asset_facts.items[*].fact_kind = ISSUER_FACT` |
| 核准的 `market_reaction_facts` | `asset_facts.items[*].fact_kind = MARKET_REACTION_FACT` |
| 核准的 deterministic calculations | `asset_facts.items[*].fact_kind = DETERMINISTIC_CALCULATION` |
| `issuer_events` | `decision_relevant_events.items` |
| derived／declared `reflexivity_blockers` | `blockers.items` |

最小輸出 surface：

```json
{
  "asset_facts": {
    "section_state": "READY | PARTIAL | BLOCKED | NOT_EVALUATED",
    "coverage_state": "COMPLETE | PARTIAL | BLOCKED | NOT_EVALUATED",
    "overlay_id": "CRT-ISSUER-001",
    "overlay_type": "NON_WEIGHTED_EVIDENCE_OVERLAY",
    "items": []
  },
  "decision_relevant_events": {
    "section_state": "READY | PARTIAL | BLOCKED | NOT_EVALUATED",
    "coverage_state": "COMPLETE | PARTIAL | BLOCKED | NOT_EVALUATED",
    "overlay_id": "CRT-ISSUER-001",
    "overlay_type": "NON_WEIGHTED_EVIDENCE_OVERLAY",
    "items": []
  },
  "blockers": {
    "section_state": "READY | BLOCKED",
    "overlay_id": "CRT-ISSUER-001",
    "overlay_type": "NON_WEIGHTED_EVIDENCE_OVERLAY",
    "items": []
  }
}
```

`items: []` 只有在 section coverage 為 `COMPLETE` 且 `empty_reason = VERIFIED_NO_MATCH` 時才可與 `READY` 並存；其餘情況必須保留 `PARTIAL`、`BLOCKED` 或 `NOT_EVALUATED`。目前 current `main` 沒有正式核准 reflexivity market-source allowlist 或 observation-window allowlist，因此市場反應事實與市場依賴公式保持 `BLOCKED`。
本版禁止加入：

- `reflexivity_score`
- BUY／SELL
- `capital_strategy`
- 自動 `asset_role`
- 第七層或新權重
- 將 blocker 空陣列解讀成已驗證正常

---

## 9. READY-TO-IMPLEMENT DELTA

> `N.S. GO` 已於 2026-08-09 收到；本節保留核准範圍，實作必須以 current-main base `d2905989f1b0957571fbc3b4a6fbf5ffcd7a9c1a` 為準縮減。

1. 將本規格納入 current `main` 的正式文件集合。
2. 以 additive amendment 記錄 overlay 對既有 generic sections 的映射與 fail-closed empty semantics。
3. 沿用 current-main `CRT_EVIDENCE_PACK_V0.2`；不升版、不新增 top-level section。
4. 新增單一 validation／calculation 模組；只實作已鎖定公式。
5. 未核准的市場來源與 observation window 一律輸出 `BLOCKED`。
6. 加入測試：身份錯配、三窗口混用、supersession、basic／diluted 混用、零填充、空陣列、重跑 hash、渠道不明、analyst 欄位保持空白。
7. 驗證 Overlay blocker 不改六層 weights、thresholds、BTC Season 與既有 mNAV 語義。
8. 保持 `Production: NOT_APPROVED`、`External Action Authority: NONE`。

### 9.1 Pre-GO hard stop（已由 N.S. GO 滿足）

在 `N.S. GO` 之前：

- 不施工。
- 不修改 GitHub。
- 不建立 branch。
- 不 commit。
- 不碰 runtime。
- 不碰 collector。
- 不碰 stash。
- 不自動建立 schema、測試、fixture 或 migration。

```yaml
final_state: IMPLEMENTED_DELTA_READY_FOR_INTEGRATION
next_authorized_event: N.S._INTEGRATION
```
