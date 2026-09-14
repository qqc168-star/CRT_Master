# Treasury Company CT V0.1（國庫公司斷層掃描 V0.1）

## 工程基準與範圍

## V0.1.1 Corrective Delta

- 每筆 CT 證據強制保存 `effective_time`、`disclosure_time`、`first_seen_time`、
  `retrieval_time` 四座時鐘。Decision Replay 僅在 disclosure 已可得時使用；
  Audit Replay 以 retrieval 可得性重建稽核視角。任一未來可見性或時鐘倒序均為
  `BLOCKED`，不得以日後修訂資料回灌過往決策。
- `source_semantic` 是必填且版本化的 binding（identity、version、effective_from、
  effective_to）。CRT formal diluted-equity mNAV、SaylorTracker diluted mNAV、
  Strategy issuer mNAV 為三條永久分線；CRT 價格狀態只接受前者，未綁定即
  `SOURCE_SEMANTIC_UNBOUND_BLOCKED`。
- SaylorTracker 只可經人工核准的 Sensor Admission Record 與 supplied Offline CSV
  Import 進入 `RESEARCH_SECONDARY`。匯入保存 provenance、raw hash、retrieval、
  first-seen 與 coverage；沒有 crawler，也永遠不是交易門檻輸入。
- Net BPS Attribution 是證據性拆解：Market Translation、Asset Action、Claim Action、
  Reserve Action、Share Denominator。Strive 沒有成熟正式語義時只能 `BLOCKED` 或
  `RESEARCH_CANDIDATE`，不能冒充正式指標。

施工時已從 GitHub（遠端版本庫）重新確認 `main`（主分支）為
`f920689524fbfd5984deae1024e9b850aee31424`。交接包的程式與補丁是研究參考；
本實作依主分支的 `CRT_CORE_CONTRACT.md`、`CRT_EVIDENCE_PACK_CONTRACT.md`、
`diluted_equity_mnav.py` 與證據包介面重新整合。

本增量補足可重複的公司每股資產、融資、資本負擔、資本轉換及管理動作證據。
它供分析員辨識器官方向分歧與成長減速，不構成估值模型、健康總分、燈號、
反身性判決、第七層或交易指令。案例 A–F（六個病理案例）均使用合成資料，
不宣稱已驗證任何年份的實際公司歷史。

## 呼叫與來源契約

`build_treasury_company_ct` 是純函式；不蒐集來源，也不存取帳戶。
上游須先驗真並正規化資料。每筆證據均需要：

- `issuer_id`：與本次公司識別碼完全一致。
- `source_ref`：非空、可由上游解析到已驗真證據的參照字串。
- `verification_state = VALIDATED`：上游驗真結果；字串本身不是來源真實性的證明。
- `effective_at_ms`：事實或已執行動作的有效時間。
- `available_at_ms`：證據已公開／可得時間，必須不早於有效時間且不晚於 `as_of_ms`。

時間沿用上游的毫秒整數介面；本模組不把只有日期的來源偽造為精確時間。
上游需明確保留日期精度與轉換口徑，不能用此介面宣稱毫秒精度的真實事件。
輸出只表示指定觀測時點的證據；不宣稱資料在未來仍新鮮或可作即時交易。
缺少來源、公司身分或時間會阻擋該筆證據，獨立有效證據保留。

所有金額為美元；`*_change_pct` 為比例（`0.1` 表示 10%），
`annual_cost_rate_pct` 為百分點單位（`12` 表示 12%）。
輸入不可含無限值、非數字、布林數值或負的存量／成本。
來源參照必須涵蓋同一筆紀錄所有已填欄位；若來源或口徑不同，須先分開驗真及正規化。

## 五器官

1. `asset_history`：持幣量與稀釋股數，`basis_ref` 指向共同的稀釋、股票分割及公司範圍口徑。
   保存個別有效存量，即使比率不可算。單筆可保留每股水平，兩筆可比較方向，
   三筆且相鄰期間等長才判定成長加速／減速。不同口徑、重複時間、
   中間無效紀錄及零分母阻擋對應比較；不跳過無效紀錄，不虛構 7 日／90 日／全年變化。
2. `funding_instruments`：每項需唯一 `instrument_id` 與 `instrument_type`。
   分離 `program_capacity_usd`、`cumulative_program_usage_usd`、`usable_capacity_usd`、
   `observed_funding_use_usd` 與 `annual_cost_rate_pct`。
   額度與累計使用必須來自同一方案版本；來源參照保存其範圍和觀測期間。
   名目剩餘額度可用減法計算，但不等於可用融資能力。
   可用額度需 `usability_basis_ref`；成本需 `cost_basis_ref`。
   `previous_cost` 必須另具來源、較早時間及相同成本口徑。
   `market_absorption_evidence` 只接受 `ISSUER_REPORTED_FUNDING_OBSERVATION` 與 `observation_ref`。
   市場反應與市場相依公式繼續受既有正式來源／窗口鎖限制，不由本模組解鎖。
3. `burden_current`／`burden_previous`：需 `basis_ref` 說明同一美元年度化成本與索取權口徑。
   年度利息加優先股配息為當期年度成本；債務本金加優先股清算索取權為優先索取權。
   缺任一分量只阻擋相應合計。現金與儲備只有同時明確
   `reserve_usable_for_carry = true`、`reserve_separate_from_cash = true` 才相加。
   覆蓋年數是靜態「可用流動性／當期年度成本」，不是現金流預測或償付能力保證。
   `maturities` 保存唯一 `maturity_id`、本金 `principal_due_usd`、`due_at_ms` 與剩餘天數；
   不從部分到期清單推論全公司總到期負擔，不生成到期風險總分。
4. `capital_conversion_events`：需唯一 `event_id`、`source`、`destination`、`amount_usd`。
   `consequence_basis_ref` 支援明確的持幣、股數、索取權、年度成本與流動性增減。
   未知增減是 `null`，不是零。普通股發行支付優先股股息，不會自動推論未來成本下降；
   現金／售幣回購的成本與索取權下降也必須有明確證據。
   不跨事件加總，避免不同事件識別碼其實對應重疊會計範圍。
5. `management_events`：需唯一 `event_id`、`action_type`、`action_ref`；只保留可驗真動作。
   管理品質與適應能力留給分析員，不讀取或生成品質分數。

兩種事件都需明確 `active_for_calculation`；已被取代的動作保留追溯但標為不參與計算。
重複識別碼會使相關事件無效，不能重複計入。

## 覆蓋與估值語義

`coverage` 可提供 `funding`、`maturities`、`capital_conversion`、`management`。
每份覆蓋證據需上述來源／公司／時間欄位、`scope_ref` 與 `coverage_state = COMPLETE`。
空清單還需 `empty_reason = VERIFIED_NO_MATCH`，否則是未知，不能聲稱沒有融資或事件。
未證明完整覆蓋時，個別有效事實依然可用，但整體範圍標為部分。

`price_financing_state` 接受既有 `build_diluted_equity_mnav` 的可用輸出，
另附公司及來源時間資料。`semantic_ref` 必須指向
`radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md`。
這是既有正式語義的參照，不建立另一套淨資產組成。
上游仍負責證券與公司映射、正式淨資產組成與對齊驗真。
本模組只保留其價格／融資貨幣狀態，無效時 `mnav = null`；它不是第六器官。

## 證據包整合與治理

`build_evidence_pack(..., treasury_company_ct_input=...)` 可選擇接入。
省略輸入時既有流程不變；提供時將六項證據（五器官及價格狀態）寫入
`asset_facts.items`，動作寫入 `decision_relevant_events.items`，逐項問題寫入 `blockers.items`。
保留既有項目與阻塞，不新增證據包頂層區塊。個別項目的 `overlay_id`、
`ct_section` 與 `evidence.state` 決定其來源及可用性，不能用整體區塊狀態抹除獨立事實。
原貢獻雜湊保存為 `upstream_overlay_hash`，合併內容重新計算 `overlay_hash` 與整包雜湊。
`COMPLETE` 只表示本次證據完整，不表示公司健康。

正式六層權重 `20 / 20 / 17 / 25 / 13 / 5`、燈號 `-60 / -35 / 35 / 60`、
未加限定的稀釋後股權 `mNAV` 語義、Production（正式生產）`NOT_APPROVED`、
External Action Authority（外部行動權限）`NONE` 均維持原狀。
本次沒有接入投資人斷層掃描、券商、實際值班部署或自動蒐集管線。
既有接力棒的 `6 / 8` 與第七項傳輸阻塞不因本功能而改變。
