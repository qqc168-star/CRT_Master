# CRT Diluted mNAV Semantic Revision（CRT 稀釋後資產淨值倍數語義修訂）

## 使用者批准及歷史邊界

- 批准日期：`2026-10-13`，日期精度；不補造批准時分秒。
- 批准者：CRT 使用者。
- 批准依據：本次「CRT 正式 mNAV 唯一定義統一｜使用者批准施工」明確裁決。
- 使用者提供的公式圖片及 StrategyTracker（財庫研究平台）定義是本次裁決的原始依據；本紀錄不聲稱圖片已另行封存或驗真。
- 本修訂取代目前程式對未限定 `mNAV` 的舊分母授權；原 `radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md` 及既有批准封印保留原始內容，不倒改歷史批准事實。
- 本次批准允許程式修改、回歸、提交、推送及合併主分支，不批准部署、券商擷取、模型外送、通知、交易或資金移動。

## 唯一正式公式

未加限定的 `mNAV` 只表示 Diluted mNAV（稀釋後資產淨值倍數）：

**稀釋後總股數 × 股票價格 ÷（BTC 持有量 × BTC 價格）。**

```text
formula_version = CRT_DILUTED_MNAV_BTC_MARKET_VALUE_V1
schema_version = CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.2
semantic_ref = radar/RELEASE/CRT_DILUTED_MNAV_SEMANTIC_REVISION_20261013.md
denominator_basis = BTC_HOLDINGS_MARKET_VALUE_USD
mnav = (diluted_shares * equity_price_usd) / (btc_holdings * btc_price_usd)
```

分子為該原始稀釋範圍的普通股市值；分母只能為該公司 BTC（比特幣）持幣市值。
分母不得扣除債務、優先股或其他索取權，不得加入現金、其他資產或普通股剩餘價值。
舊欄位 `diluted_equity_market_cap_usd` 與 `asset_nav_usd` 若為相容性而保留，只能分別是上述四項元件重算的分子與分母別名；兩個總額及一個比值本身不能取得正式資格。

## 元件來源、股數口徑及時間資格

正式計算只接受 MSTR（Strategy 普通股）及 ASST（Strive 普通股）各自合格的四項原始元件：

- `diluted_shares`：來源的原始稀釋股數，保存 `basis_ref`、非空 `dilution_scope` 及明確的 `coverage_state = COMPLETE`。不得自行增減股份，ASST（Strive 普通股）的傳統認股權證排除範圍必須明示；保存報告範圍不代表該範圍已獲批准為完整正式稀釋口徑。缺失或部分覆蓋不能由接入器推定完整。
- `equity_price_usd`：美元股票價格，保留完整交易日收盤、盤前或即時報價的來源語義。
- `btc_holdings`：同一公司、同一資產範圍的 BTC（比特幣）持有量。
- `btc_price_usd`：合格美元 BTC（比特幣）價格，不能用未核驗研究假設替代。

每項須具可解析的來源參照、原始 SHA256（雜湊）、驗真資格及四座證據時鐘：有效時間、揭露時間、首次取得時間、擷取時間。四項有效時點必須對齊，四座時鐘順序須有效，擷取時間不得晚於本次驗證時間。不得替未證明的 MSTR（Strategy 普通股）ADSO（假設稀釋流通股數）補造有效時間。

缺值、零值、非有限值、來源不合格、時點錯配、稀釋範圍不明或總額與元件不符時，受影響的正式估值主張維持 `BLOCKED`。獨立有效的公司健康及研究證據保留，未知不當零，不以舊快照補成當次合格。

## 版本、歷史分布與下游一致性

舊版資料保留其原始語義、版本、來源、時間及稀釋範圍。舊 `CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.1` 或不明分母資料，不得只更換版本字串或重新命名便升格；保留為明確標示的舊版研究證據，不能混入新正式歷史分布。

已能證明使用同一公式、同一公司、同一稀釋與價格口徑的合格原始資料，才可經現有計算器重算為新版本。若四項原始元件或歷史可見時間無法驗真，不得宣稱重算完成。同公式的 StrategyTracker（財庫研究平台）研究數字仍是研究來源，公式相同不賦予正式來源權威。

沿用既有歷史百分位演算法：排除當前值，至少二十筆較早且獨立的可比較觀測，`100 * count(previous <= current) / count`。五週變化沿用三十五日前、前後三個日曆日窗口及較早值優先的選取規則。自有歷史須同公式版本、同公司、同稀釋範圍及同價格口徑，不混入舊分母或無法核驗的值。既有明確標示身分的跨公司基準比較仍獨立呈現，須通過同公式與可比較口徑驗證，不得混入公司的自有歷史分布。

Treasury Company CT（財庫公司斷層掃描）、公司健康、配置分析、證據包、GPT（分析模型）橋接及資本建議均沿用這一正式定義與資格。研究估值、發行人自訂倍數及舊版值必須明示限定，不能支持缺失的正式買進資格。

## 獨立公司健康證據及其餘治理鎖

債務本金、優先股請求權、年度資本成本、可用現金、受限儲備、其他資產及每股剩餘經濟價值，繼續依既有公司健康契約獨立呈現；不得取名或冒充本修訂的 `mNAV`。

本修訂只改變上述正式 `mNAV` 語義，不改變：

- 六層權重：`20 / 20 / 17 / 25 / 13 / 5`。
- 燈號閾值：`-60 / -35 / 35 / 60`。
- BTC（比特幣）正式季節、正式來源及已批准季節封印。
- 四季配置與使用者資本軌道確認要求。
- `production = NOT_APPROVED`。
- `external_action_authority = NONE`。
- `capital_decision_authority = USER_ONLY`。
- `machine_execution = FORBIDDEN`。
- 既有 Runtime（執行環境）、排程及 stash（暫存修改）。

本修訂不代表第八項實戰驗收完成，原進度維持 `7 / 8 = 87.5%`。
