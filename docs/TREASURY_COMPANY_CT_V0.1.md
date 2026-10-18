# Treasury Company CT V0.1（國庫公司斷層掃描 V0.1）

## 工程基準與範圍

## V0.1.1 Corrective Delta

- 每筆 CT 證據強制保存 `effective_time`、`disclosure_time`、`first_seen_time`、
  `retrieval_time` 四座時鐘。Decision Replay 僅在 disclosure 已可得時使用；
  Audit Replay 以 retrieval 可得性重建稽核視角。任一未來可見性或時鐘倒序均為
  `BLOCKED`，不得以日後修訂資料回灌過往決策。
- `source_semantic` 是必填且版本化的 binding（語義綁定：identity、version、effective_from、
  effective_to）。CRT（第一顆比特幣決策研究體系）正式 Diluted mNAV（稀釋後資產淨值倍數）、
  財庫研究平台數字與發行人自訂倍數保持來源／權威分線；公式相同不代表來源資格相同。
  CRT（第一顆比特幣決策研究體系）價格狀態只接受目前正式版本，未綁定即
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
另附公司及來源時間資料。`semantic_ref` 必須指向使用者於 `2026-10-13` 批准的
`radar/RELEASE/CRT_DILUTED_MNAV_SEMANTIC_REVISION_20261013.md`，
`formula_version = CRT_DILUTED_MNAV_BTC_MARKET_VALUE_V1`。
唯一公式為 `(diluted_shares * equity_price_usd) / (btc_holdings * btc_price_usd)`。
四項元件須具來源、原始雜湊、四座時鐘及同一有效時點；稀釋股數須保存原始
`basis_ref`、`dilution_scope` 及明確 `coverage_state = COMPLETE`，不自行補股或排除股份。
本模組重新核驗元件及其相乘總額；只有兩個總額或一個比值不能取得正式資格。
相容欄位 `asset_nav_usd` 只能是合格 BTC（比特幣）價格乘持幣量的派生市值。
債務、優先股、現金與剩餘價值維持獨立公司健康證據，不增減此分母。
原 `radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md` 仍為歷史批准紀錄，
不再單獨證明本次正式公式；舊版或未知分母值不能重新標記後升格。
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
未加限定的 `mNAV` 遵循上述已批准修訂；Production（正式生產）`NOT_APPROVED`、
External Action Authority（外部行動權限）`NONE` 均維持原狀。
本次沒有接入投資人斷層掃描、券商、實際值班部署或自動蒐集管線。
既有接力棒的 `6 / 8` 與第七項傳輸阻塞不因本功能而改變。


### Retained official issuer source binding

`daily_evidence_runner --issuer-ct-archive <acceptance-root>` reads the existing
`sec-disclosures/manifest.json` and hashed raw HTML without fetching or changing
the archive. It checks issuer/accession identity, raw SHA-256, SEC acceptance and
proven local retrieval. Retrieval after the replay time is excluded. Date-only
SEC observations reuse the existing UTC date conversion and retain DATE precision;
these values are not claims of intraday effective timestamps. First seen means
first proven local archive retrieval, not presumed public availability.

ASST AFDS excludes Traditional Warrants; comparison uses a single filing's paired
observations, without assuming equivalence across splits or denominator changes.
Conflicting same-date values remain blocked. MSTR Ledger reported observations
remain NOT_CT_BOUND / ADSO_EFFECTIVE_TIME_UNRESOLVED, with their original hashes.
They remain available through the existing `--issuer-ratio-proof` observation
lane; SEC period funding uses and cash/reserve snapshots independently feed CT.
SATA forward dividend terms never populate September historical carry. Missing
principal, liquidation terms, costs or usable funding capacity remain missing.
Nominal remaining capacity is distinct from usable capacity. Capital routes are
not summed into a causal return; cash-funded and issuance-funded legs remain
separate and unknown consequences stay null.

CT BTC/share facts now supply the existing common-equity health projection when
valuation inputs are absent, after local-visibility and basis checks. Conflicting
CT/valuation values block that claim. Formal mNAV, action authority and Bridge
limits are unchanged. Source binding diagnostics remain in Evidence Pack facts
and claim-scoped blockers; no second fact database is created.


PR #126 final correction: cash conflicts are compared across documents by issuer,
effective date, currency, cash definition and accounting scope, independently of
`basis_ref`. Conflicting components and dependent liquidity totals are blocked;
other verified components and BTC/share remain available. Conflicting originals
and references remain in source-binding diagnostics; no revision is inferred.

The retained MSTR/ASST capital-flow announcements describe period aggregates.
Their amounts, quantities and explicit start/end dates remain in
`ISSUER_CT_SOURCE_BINDING` facts with `execution_time=null` and
`PERIOD_AGGREGATE_EXECUTION_TIME_UNRESOLVED`. They do not enter CT conversion or
management action calculations. Period end is never execution effective time.
Funding-use observations retain period scope; cash/capacity snapshots retain
as-of semantics. Missing/ambiguous periods block the funding-use claim.
MSTR ADSO effective time remains unproven; ASST stock-count changes and future
SATA dividend terms alone do not establish funding proceeds or usable capacity.

### Dated Strategy ADSO research（Strategy 日期股數研究）

The optional `shares-raw/retrieval-*.json` archive input retains independently
hashed official `https://www.strategy.com/shares` and `/notes` response bytes.
Each `shares` / `notes` receipt has `source_url`, `http_status`, `sha256`, `length`,
`first_seen_at_ms`, and `retrieved_at_ms`; raw files are `<name>-<sha256>.html`.
The existing issuer table-coordinate parser separates the ADSO colspan from
FDSO, including when their date headers coincide. Positive paired BTC / ADSO
values retain their as-of day, rounded-thousands precision, conversion components
and original dilution scope. Date sorting never assigns a public disclosure time.

These are `RESEARCH_ONLY` retrospective observations in the existing CT
`source_binding` and Evidence Pack facts, not `asset_history`, a formal Company
Health release, or formal valuation inputs. The last two dated ADSO columns are
compared within one archived snapshot; historical document revisions are not
merged into a point-in-time series. First proven local retrieval is preserved;
the current website cannot prove past public availability. An invalid receipt
blocks its research observation while unrelated SEC facts remain available.

ADSO assumes conversion of all convertible notes / convertible preferred,
options and RSU/PSU settlement; FDSO limits note / preferred conversion by market
price. Neither is GAAP diluted weighted-average EPS shares. Assumed conversion
does not prove actual debt extinguishment. A residual scenario must still pass
the existing complete-claims and coherent-capital-structure checks; it must not
both assume conversion dilution and deduct the same supposedly converted debt.
No debt, preferred claims or cash adjustment enters the CRT formal mNAV formula.
Unknown disclosure clocks and formal dilution / price alignment remain blocked.

### Independent Strategy period facts（Strategy 獨立期間事實）

MSTR 的 SEC 主文件明確引用附件時，可在同一封存 manifest（資料清單）中加入
附件項目及 `parent_document`（主文件的 `primary`、`raw_sha256`、`retrieved_at_ms`）。
附件原文使用 `MSTR-<accession>-<primary>.html`，主文件原路徑不變。讀取器驗證
同一 accession、CIK、原始主文件連結、兩份原文雜湊、接受時間及實際本機可見時間。
未引用、竄改或尚未取得的附件不能提供事實；不把附件 bytes（位元組）拼接成主文件。

ATM（市價增資）購幣、ATM 回購 STRC、USD Cash（美元現金）購幣與現金回購 STRC
分別讀取，不依賴另一用途或餘額截面存在。新增普通股及已披露淨募集額、BTC 購入
總數／成本、STRC 回購股數／支付總額留在既有 `source_binding`，標示期間、原文
來源、數值口徑與重疊關係。來源淨款、用途分項與購買總額不能重複相加；四捨五入
總成本也不能重算或取代發行人平均價。未披露的回購資金來源、消滅請求權、年度
負擔變化及每筆購幣的 BTC 數量分配仍未知。

原有保護保持：`execution_time = None`、不提供行動用 `effective_time`、
`active_for_calculation = false`；期間末或公告時鐘都不是執行／交割時間。
USD Reserve（美元儲備）與 USD Cash 分離；期間事實不自動成為可用資本、
Company Health（公司健康）放行、ADSO 生效證明或完整每股剩餘價值。

### Strive financing lifecycle and dated fixed obligations（Strive 融資階段與定期義務）

既有 Strive 發行人接入器的 `SATS_TERMS` 模式使用已核驗的 Strive CIK
`0001920406`，保留原文雜湊、證券身分、公告可見時間、條款、順位原文、CUSIP
及上市日期資格。EchoStar 舊 `SATS` 不屬於該身分。擬上市或預計交易日不等於
已上市；`ANNOUNCED`、`PRICED`、`SETTLED` 分開。預計交割日期經過，不會自動
變成交割證明。已交割公告本身也不證明募集款已入帳、淨額、實際流通量或部署。

`build_archived_issuer_ct_inputs()` 沿用原 CIK／原始文件雜湊檢查，把可解析的
SATS 公告接到 `preferred_funding_events`；沒有完整條款的文件只保留獨立已知值。
官方 FWP（發行人自由書寫招股文件）未內嵌 CIK 時，須另外提供同一封存內的
`ASST-submissions.json`、`issuer_index_raw_sha256` 及實際取得時間；復用既有 SEC
索引解析器核對 CIK、發行人名稱、accession、文件網址與接受時間。任何一項不符
即拒絕，不能只憑 SATS 代碼或檔名建立身分。
該輸入可供既有 CT 的 `funding_engine` 及 Treasury Valuation（財庫估值脈絡）
共用 `build_preferred_funding_attribution()`。未交割事件不能產生已實現的資產、
請求權、費用或資金轉換。新交割事件須有真實交割時間與來源；舊事件沒有階段
欄位時保留原契約計算，但明示 `LEGACY_NOT_SETTLEMENT_PROOF`，不冒充新交割證明。

同輪 `round_accounting` 分列毛額、費用、淨額、新增／消滅請求權、購幣、其他部署、
舊請求權償付現金及未部署現金；必須具來源歸屬依據並完成金額核對，才能標為
`SOURCE_BOUND_RECONCILED`。償付現金與消滅的請求權分開，不重複扣除；同期變化
不能自動形成因果歸屬。有效優先股融資成本仍只使用原有的年度股息／已驗證淨額。
年度成本不當成當日已支出現金。

`fixed_obligations` 是既有 `capital_burden_resilience` 的附加日期明細，不是新引擎。
每筆須有唯一經濟付款參照、金額依據、到期日、四座時鐘、官方來源分類及義務種類。
已確認支付與未宣告條款情境分列；優先股須有已發行時間證據。30／90／180 日窗口
保留已知小計；完整合計及足額結論另需 `ALL_FIXED_OBLIGATIONS` 的完整覆蓋。
可用流動性另需用途、有效期及其來源依據。未知現金不填零；不完整明細不能證明
沒有缺口。已知義務大於合格現金時，可以指出最早已證實的最低缺口日期。
但公司缺口還須證明 `ALL_USABLE_LIQUIDITY` 完整涵蓋可用流動性；只有一部分現金
不足時，只顯示該現金範圍差額，不能宣稱公司全部資金不足。
這不是 Corporate Survival Runway（全公司生存年限），不包含預測新融資或出售 BTC。

精簡投影另保留既有 `DEBT_PRINCIPAL` 的 `principal_schedule_evidence`，包括 180 日以外
的日期、金額、原 `recognition`、來源參照及四座時鐘。此為傳遞，不新增計算、當前
本金驗證或健康規則。未行使回售權的假設只能使用 `UNDECLARED_TERMS_SCENARIO`
研究情境，不能放入 `maturities` 或提升為 `CONFIRMED`；實際行使、結算或註銷另須
獨立來源證明。部分／全部行使假設分別重播，不能把互斥假設加總。歷史本金只是
其來源有效日的參照，不因重播升格為當前或未來確定餘額。短期窗口為零不代表
沒有遠期本金風險；未知可用現金及不完整付款表繼續阻擋足額與缺口判斷。
USD Reserve 的用途資格不能被自由現金替代；假設轉股與剩餘債務須沿用既有一致
資本結構檢查，不能對同筆已假設轉換本金同時扣債並計入完整轉股稀釋。

`qualified_usable_liquidity_usd` 保留原 carry（股息／利息）用途資格，不代表本金用途
已核准。確認本金進入某視窗時，該已驗證、未過期的流動性來源還須明示
`liquidity_usable_for_principal=true` 及非空 `principal_usability_basis_ref`，涵蓋計入的
整個資金池。旗標與字串本身不構成資格；還必須提供 `principal_usability_evidence`
清單，以既有 `_metadata(..., AUDIT_REPLAY)` 驗證發行人、非空來源、上游
`VALIDATED` 資格、四鐘與來源語義。每筆須具既有官方 `source_class`，
`permitted_use=DEBT_PRINCIPAL`，非空 `basis_ref` 與上述用途依據一致，且
`valid_until_ms` 及語義有效期涵蓋驗證時點。這是重用已驗真輸入契約，不是
下載器或自我簽署的來源驗證；上游必須保留原始證據與驗真血統。

逐筆 `component=USD_CASH / USD_RESERVE`、`amount_usd`、`liquidity_source_ref`
及 `liquidity_effective_time` 必須精確對應本次已驗真的餘額元件、來源及有效日。
計入的 Cash（含已知零額）及獨立可用 Reserve 均須各有證明；重複、未知元件、
錯配金額、過期或尚不可見的證明不能合格。未計入資金池的 Reserve 不要求本金
資格，但不能將僅限股息／利息的 Reserve 併入已獲本金資格的自由現金。
合格元件的來源證明仍保留，不因另一元件缺證而抹除；整池資格必須完整覆蓋。
包含 Reserve 時必須有適用的本金用途批准，不能以自行標籤或雜湊代替來源證明。
欠缺此依據，相關視窗的 `liquidity_use_qualified=false`，足額餘額及
缺口均為 null，確認付款仍保留；先前不含本金的股息／利息視窗仍可獨立驗證。
`principal_liquidity_qualified`、用途依據與逐項合格來源證明沿既有公司健康投影傳遞，不另建資金配置器。

附加脈絡進入原 Company Health（公司健康）六維及配置投影，但不改六維方向、不
產生健康放行或配置傾斜。完整來源留在既有 Evidence Pack（證據包）區段，摘要
沿用原資本分析投影；不新增頂層、第三釵、正式季節、分數或交易權限。
