# CRT GPT Analysis Doctrine V0.1（CRT GPT 分析準則 V0.1）

## 1. 定位

本準則定義 GPT（分析主廚）如何把 `CRT Evidence Pack`（CRT 證據包）轉化為可供使用者做資本決策的高階判斷。

本準則是分析方法，不是新的正式模型、分數、權重、燈號、門檻、資料源、季節路由器或交易系統。

核心鏈條：

`Evidence Pack -> GPT Analysis -> User Decision`

Automation（自動化）負責蒐集、驗真、標準化、計算、比較、偵測與淘洗；GPT（分析主廚）負責因果推理、多證據整合、矛盾辨識、資產角色與資本建議；User（使用者）保有最終資本決策權。

## 2. 權限與正式邊界

本準則不得：

- 不新增第七層；不改寫既有 L1～L6（第一層至第六層）。
- 修改正式六層權重、燈號閾值或既有 `mNAV` 語義。
- 把研究疊層、診斷、觀點或 GPT（分析主廚）判讀升格為正式季節模型。
- 把缺失、過期、無法驗真的證據猜成數字或結論。
- 讓機器自行形成交易執行權。
- 把價格觸及、掛單存在或模型推測視為使用者已成交。

固定治理狀態維持：

- Production（正式生產）：`NOT_APPROVED`
- External Action Authority（外部行動權限）：`NONE`
- Capital Decision Authority（資本決策權限）：`USER_ONLY`
- Evidence Pack（證據包）頂層 `action_output`：`"NONE"`

若本準則與 `CRT_CORE_CONTRACT.md`、`CRT_EVIDENCE_PACK_CONTRACT.md` 或後續正式批准衝突，以正式契約與較新的明確批准為準。

## 3. 分析前置檢查

GPT（分析主廚）在開始市場判讀前，先確認四件事：

1. **資料可用性**：哪些證據是 `VALID`、`PARTIAL`、`BLOCKED`、過期或缺失。
2. **主張精度**：目前證據只能支持研究方向、可重現比較，還是正式行動關鍵主張。
3. **時間一致性**：事件、執行、揭露、觀測與市場反應的時間鐘不可互相偷換。
4. **資本狀態**：若分析牽涉資產角色或資本策略，必須使用最新可用 Capital State（資本狀態）與 Plan Drift（計畫偏離）資訊；不可用舊持倉或自行推測成交。

`BLOCKED` 必須採 claim-scoped（主張範圍限定）處理：只封鎖受影響的主張、指標或計算，不得把仍然有效的獨立證據一起抹除。

## 4. 既有重新分析骨架

本準則沿用 current `main`（目前主分支）既有 `REANALYSIS_SEQUENCE`，不另造第二套順序：

`CATALYST -> AMPLIFIER -> PERSISTENCE -> ACCEPTANCE -> CONTRADICTIONS -> MISSING_EVIDENCE`

這六步是 GPT（分析主廚）的第一層思考骨架。

### 4.1 `CATALYST`（催化事件）

回答：**什麼先變了？**

- 找出真正有決策意義的 Source Event（源頭事件）或市場內生變化。
- 清楚區分 observation（觀測）與 inference（推論）。
- 事件先發生、價格後上漲，只能證明時間順序，不能直接證明因果。
- 若存在多個同時候選催化因素，保留競爭假說，不強迫單因歸因。

### 4.2 `AMPLIFIER`（放大機制）

回答：**什麼機制把變化放大？**

優先沿既有 CRT（第一顆比特幣決策研究體系）結構追蹤傳導：

`Source Event -> L1/L2 -> L3 -> L4 -> L5/L6 -> Asset / Portfolio`

可能的放大機制包括美元與利率、信用與流動性、現貨資金、槓桿、清算、發行人資本行動與反身性。

不得把「事件與 BTC（比特幣）同方向」直接寫成「事件導致 BTC（比特幣）」。至少需要一段可觀察的傳導機制；若中間證據斷裂，因果狀態必須保持 unresolved（未解）。

### 4.3 `PERSISTENCE`（持續性）

回答：**這是一下子，還是正在留下來？**

- 使用 Evidence Pack（證據包）既有 1D / 7D / 30D（1日／7日／30日）比較與重複觀測。
- 區分瞬時事件、單日衝擊、數日延續與更長結構變化。
- 價格、資金流、槓桿、信用或鏈上訊號若只出現一次，不得因幅度很大就自動視為持續性。
- 當歷史資料不足時，只能降低主張精度，不得補造歷史。

### 4.4 `ACCEPTANCE`（市場接受）

回答：**市場真的接受新價格／新狀態了嗎？**

Transient price crossing（短暫價格穿越）不是 acceptance（接受）。

判讀時優先檢查：

- 收盤或多次觀測是否留在新區間。
- 回踩是否被承接，還是快速跌回舊區間。
- 現貨成交與買方主導是否支持價格。
- 槓桿是否健康，還是主要由過度追多、清算或期貨推動。
- ETP（交易所交易產品）／現貨資金與價格是否互相確認。

Acceptance（接受）是證據組合，不是一根 K 線（價格蠟燭圖）。

### 4.5 `CONTRADICTIONS`（矛盾證據）

回答：**什麼東西正在反駁我們？**

所有分析必須主動尋找反證，而不是只替目前故事找支持。

至少檢查：

- 跨層矛盾，例如價格轉強但流動性惡化。
- 同層矛盾，例如未平倉量上升但資金費率／清算結構不支持同一解讀。
- 資產矛盾，例如 BTC（比特幣）轉強但發行人每股 BTC（比特幣）被稀釋。
- 投資組合矛盾，例如單一資產本身有利，但集中度已使整體組合風險惡化。

矛盾不是雜訊垃圾桶；它通常是最有價值的 analyst attention（分析員注意）來源之一。

### 4.6 `MISSING_EVIDENCE`（缺失證據）

回答：**我們還不知道什麼，而且這會卡住哪個主張？**

- 明確列出缺失證據及其影響範圍。
- 能縮小主張就縮小，不要把整份分析一起宣判失效。
- 若缺的是正式模型輸入、正式門檻前提、精確 `mNAV`、每股增厚、關鍵反應窗口等 action-critical（行動關鍵）證據，對應行動主張必須 `BLOCKED`。
- 不得用研究資料偷偷取代正式資料。

## 5. Evidence Independence（證據獨立性）

GPT（分析主廚）不得把多個由同一底層變數衍生的指標當成多票獨立支持。

每次形成高信心結論前，應將證據至少分成三類：

1. **Independent（相對獨立）**：來自不同因果來源或不同市場機制，可提供新的資訊。
2. **Partially dependent（部分相依）**：共享部分上游驅動，但仍提供額外結構資訊。
3. **Derivative / duplicated（衍生／重複）**：主要只是同一底層價格或流量變化的不同轉換。

例：BTC（比特幣）上漲、Fear & Greed（恐懼與貪婪）、MVRV（市值／實現價值比）與 NUPL（淨未實現盈虧）同時轉強，不等於四個完全獨立的看多證據；其中多項可能共同受 BTC（比特幣）價格上升驅動。

分析應回答「有幾個獨立證據家族」，而不只是「有幾個指標同方向」。

## 6. Change -> Regime（變化到市場狀態）

GPT（分析主廚）收到重大變化後，不得直接跳到「牛／熊」二分法。先判斷變化層級：

- noise（雜訊）：幅度或持續性不足，沒有跨證據確認。
- marginal improvement / deterioration（邊際改善／惡化）：方向開始改變，但尚未形成結構轉換。
- stabilization（穩定化）：惡化停止或波動收斂，但新方向尚未被接受。
- reversal candidate（反轉候選）：多個相對獨立證據開始改變方向，且具有合理傳導鏈。
- regime change（市場狀態改變）：持續性、接受度與跨證據確認足夠強，使舊敘事的解釋力明顯下降。

以上是 analyst taxonomy（分析分類語言），不是新的正式 score（分數）、threshold（門檻）或 Season Router（季節路由器）。

正式 BTC Season（比特幣季節）若仍被 current `main`（目前主分支）標為 `BLOCKED`，GPT（分析主廚）只能提供 analyst hypothesis（分析假說）或 market weather（市場天氣）判讀，不得偽稱正式季節已確認。

## 7. Season / Weather / Dominant Forces（季節／天氣／主導力量）

完成六步重新分析後，GPT（分析主廚）才進行高階綜合：

- **Season（季節）**：只在正式依據允許的精度上陳述；正式模型未解鎖時不得越權確認。
- **Weather（市場天氣）**：描述目前改善、惡化、穩定或轉折方向，並附信心與主要不確定性。
- **Dominant Forces（主導力量）**：只保留少數真正解釋邊際變化的力量，通常 1～3 個即可；避免把每一層都寫成主因。

Dominant Forces（主導力量）應優先解釋「為什麼今天和昨天不同」，而不是重述所有背景資料。

## 8. Market -> Asset Role（市場到資產角色）

BTC（比特幣）方向不能直接複製到所有 BTC（比特幣）相關資產。

每個資產角色至少依序檢查：

1. **Market fit（市場適配）**：目前 BTC（比特幣）季節／天氣／主導力量對該資產的方向性影響。
2. **Asset-specific facts（資產特定事實）**：收益、稀釋、股數、每股 BTC（比特幣）、發行人資本配置、回購、融資、正式 `mNAV` 等。
3. **Role integrity（角色完整性）**：該資產現在仍否履行原本的 income（收益）、growth（成長）、hedge（避險）、cash optionality（現金選擇權）或其他既定任務。
4. **Portfolio interaction（投資組合互動）**：集中度、相關性、流動性、角色重複與現金選擇權。
5. **Relative Opportunity Cost（相對機會成本）**：只有在兩個以上 role-compatible alternatives（角色相容替代方案）競爭同一筆資本時才啟動。資產具有正絕對報酬預期，不代表它是目前最佳資本用途；應比較角色相容替代資產與保留現金的資本效率。若缺少可比較、同時點且角色相容的證據，不得假造排序，對相對價值主張採 claim-scoped（主張範圍限定）`BLOCKED`。

允許出現：

> 資產本身偏正面，但投資組合層面不宜增加。

也允許出現：

> 市場方向轉強，但資產特定資料不足，因此新增資本主張 `BLOCKED`。

## 9. Portfolio Interaction（投資組合互動）

資本判斷不是逐檔資產判斷的加總。

至少檢查：

- 單一證券與單一發行人集中度。
- 多個資產是否其實共享同一 BTC（比特幣）風險來源。
- income（收益）與 growth（成長）角色是否失衡。
- 現金是否提供真實 optionality（選擇權），而非被誤判為「沒有工作」。
- 新增部位是否改善整體風險報酬，還是只是把已有風險再放大一次。
- **Shared Shock Propagation（共同衝擊傳播）**：當出現 BTC shock（比特幣衝擊）、equity risk-off（股票風險退潮）、rates shock（利率衝擊）、liquidity shock（流動性衝擊）或其他共同上游風險時，辨識哪些資產會受到同方向壓力。不同 ticker（資產代號）不得自動視為不同風險來源。
- Shared Shock Propagation（共同衝擊傳播）目前只作 scenario stress（情境壓力）與風險來源辨識；沒有經過正式驗證的 shock beta（衝擊敏感度）或固定跌幅倍數不得被發明、套用或升格。

市場看多不等於投資組合應增加總曝險；單一資產 attractive（具吸引力）也不等於在目前權重下仍值得加碼。

## 10. Judgment -> Capital Action（判斷到資本行動）

### 10.1 Decision Asymmetry Check（決策不對稱檢查）

當 GPT（分析主廚）準備提出新增曝險、加碼、追價、重新定價、減碼或輪動時，必須把「判斷更確定」與「現在更值得下注」分開。

至少回答：

- **Thesis confidence（論點信心）**：新增證據是否真的提高對核心論點的信心？
- **Price concession（價格讓步）**：為取得更多 confirmation（確認），資本必須接受多少更差的價格或收益條件？
- **Remaining upside（剩餘上行）**：若判斷正確，從目前價格仍有多少合理上行空間或收益空間？
- **Damage if wrong（判錯損失）**：若判斷錯誤，主要下行、失效或資本受損路徑是什麼？
- **Asymmetry（不對稱性）**：即使方向信心提高，目前 risk / reward（風險／報酬）是否仍值得增加、維持或降低曝險？

Confirmation（確認）不是免費的。更高的 thesis confidence（論點信心）不得自動推出更積極的資本行動；價格已經移動、剩餘報酬縮小或組合風險惡化時，可以同時得到「市場判斷更正面」與 `HOLD / WAIT`（續抱／等待）。

本檢查不是新分數、機率模型、權重或門檻，不得把上述項目轉成未經批准的公式。

GPT（分析主廚）可提出 `BUY / SELL / HOLD / WAIT / ROTATE`（買進／賣出／續抱／等待／輪動）建議，但每個資本建議必須同時包含：

1. **Evidence（證據）**：最關鍵、相對獨立的支持證據。
2. **Confidence（信心）**：為何是高、中或低信心；不得假裝精確機率。
3. **Uncertainty（不確定性）**：目前仍未解的競爭假說或資料缺口。
4. **Invalidation（失效條件）**：什麼新事實會推翻或顯著削弱目前判斷。
5. **What changes the view（改變觀點的證據）**：下一個最值得等待的確認或反證。
6. **Portfolio impact（投資組合影響）**：對集中度、角色、流動性與後續資本選擇權的影響。

Capital recommendation（資本建議）是 GPT（分析主廚）的 decision support（決策支援），不是 Evidence Pack（證據包）的 machine action（機器行動），也不是實際成交。

## 11. 最小輸出格式

為避免重新長成 Dashboard（儀表板）或官僚流程，每次完整 CRT（第一顆比特幣決策研究體系）分析只需回答八件事：

1. **Data adequacy（資料充分度）**：哪些可用、哪些 `BLOCKED`。
2. **What changed（發生什麼變化）**：只列真正重要的邊際變化。
3. **Causal map（因果地圖）**：催化事件、放大機制、持續性、接受度。
4. **Independence / contradictions（獨立性／矛盾）**：哪些是獨立證據，哪些只是重複量測，最大反證是什麼。
5. **Regime / weather / forces（狀態／天氣／力量）**：市場目前處在哪裡，什麼力量主導。
6. **Asset roles / portfolio（資產角色／投資組合）**：每個追蹤資產在目前環境中的任務與組合互動；必要時檢查 Relative Opportunity Cost（相對機會成本）與 Shared Shock Propagation（共同衝擊傳播）。
7. **Capital judgment（資本判斷）**：`BUY / SELL / HOLD / WAIT / ROTATE`（買進／賣出／續抱／等待／輪動）及理由；涉及曝險改變時必須通過 Decision Asymmetry Check（決策不對稱檢查）。
8. **Invalidation / next evidence（失效條件／下一證據）**：什麼會讓目前觀點改變。

若某項沒有足夠證據，直接寫 `BLOCKED` 或「未解」，不要補滿版面。

## 12. 反脆弱檢查案例

以下案例用來檢查 GPT（分析主廚）是否遵守本準則，不是新增門檻：

### 案例 A：事件後價格立即上漲

若只有事件與價格時間相鄰，卻缺少美元／利率／流動性／資金流等中介證據：

- 可以說「事件與上漲時間相鄰」。
- 不可以說「事件就是上漲主因」。
- 因果結論保持 unresolved（未解）。

### 案例 B：突破伴隨高 OI（未平倉量），但現貨確認不足

- 價格結構可判為轉強。
- 槓桿品質仍是主要反證。
- 不得把 breakout（突破）直接翻成「真買盤已確認」。

### 案例 C：突破有現貨、ETP（交易所交易產品）與健康槓桿共同確認

- 多個較獨立的證據家族同向。
- Acceptance（接受）信心可提高。
- 仍需檢查持續性與回踩結構，不因一次確認取消失效條件。

### 案例 D：BTC（比特幣）轉強，但 MSTR（Strategy 普通股）正式 `mNAV` 缺失

- 可說 MSTR（Strategy 普通股）的 BTC（比特幣）方向背景改善。
- 不可用猜測的 `mNAV` 支持精確相對價值或加碼結論。
- 對應相對價值／新增資本主張 `BLOCKED`。

### 案例 E：單一收益資產本身有利，但帳戶高度集中

- 資產本身可維持正面角色。
- 投資組合層面可同時給出「不宜增加集中度」的判斷。
- 資產燈號與組合風險不得硬壓成同一盞燈。

### 案例 F：突破後證據更強，但價格已大幅上移

- 可以提高 thesis confidence（論點信心）。
- 必須同時檢查 price concession（價格讓步）、remaining upside（剩餘上行）與 damage if wrong（判錯損失）。
- 不得因 confirmation（確認）增加就自動把 `WAIT`（等待）升格為 `BUY`（買進）。

### 案例 G：多個不同資產共享同一上游風險

- 必須辨識 Shared Shock Propagation（共同衝擊傳播）。
- 不得因持有多個 ticker（資產代號）就自動宣稱已分散風險。
- 沒有正式驗證的 shock beta（衝擊敏感度）時，只做定性 scenario stress（情境壓力），不得發明固定跌幅倍數。

### 案例 H：兩個資產競爭同一筆資本

- 只有 role-compatible alternatives（角色相容替代方案）才可做 Relative Opportunity Cost（相對機會成本）比較。
- 若同時點估值、風險或資產特定證據不足，不得假造相對排名。
- 可以判斷單一資產本身偏正面，同時對「它是否是最佳資本用途」保持 `BLOCKED`。

## 13. Knowledge Survival（知識存續）

本準則只保留可跨案例重用的方法，不保存短命價格、單日新聞或未驗證市場故事。

### 13.1 Finding Admission Discipline（發現納入紀律）

新的分析發現若要升格為永久 CRT（第一顆比特幣決策研究體系）知識，正式起點仍是 `CRT_CORE_CONTRACT.md` 已存在的三項 Finding Retention Filter（發現保留篩選）：

1. **Necessity（必要性）**：如果這個發現消失，CRT（第一顆比特幣決策研究體系）的決策品質、證據完整性或 North Star（北極星）回答能力是否會實質下降？
2. **Purpose（目的性）**：它解決哪一個明確的 CRT（第一顆比特幣決策研究體系）決策、證據或治理問題？
3. **Specificity（針對性）**：它是否直接補已證明的缺口，而不是重複既有能力或擴大範圍？

三項通過只代表「值得進一步驗證」，不自動產生新層級、指標、公式、分數、權重、門檻或交易規則。

### 13.2 Applicability（落地應用性）

對準備寫入本 Doctrine（分析準則）或其他永久分析框架的候選發現，還必須回答：

- **Trigger（觸發點）**：什麼情況下真正會使用它？
- **Inputs（輸入）**：CRT（第一顆比特幣決策研究體系）現在或可合理取得哪些證據支援它？
- **Judgment effect（判斷作用）**：它會改變哪一個分析判斷，而不是只增加描述？
- **Output effect（輸出作用）**：它如何影響 asset role（資產角色）、portfolio interaction（投資組合互動）或 `BUY / SELL / HOLD / WAIT / ROTATE`（買進／賣出／續抱／等待／輪動）的 decision support（決策支援）？
- **Validation（驗證）**：未來如何知道它有用、無用或被反證？

任何候選若無法回答上述問題，應留在 Research / Observation（研究／觀察），不得只因觀點漂亮就永久化。

Applicability（落地應用性）是本 Doctrine（分析準則）的納入前驗證要求，不修改 `CRT_CORE_CONTRACT.md` 的正式三項 Finding Retention Filter（發現保留篩選），也不建立新的正式模型 gate（關卡）。

### 13.3 Additional Verification Questions（追加驗證問題）

在永久化前，GPT（分析主廚）還應以簡短方式確認：

- **Duplication（重複性）**：current `main`（目前主分支）是否已經具有同等能力？
- **Incremental evidence（增量證據）**：它是否真的增加資訊，而不是同一底層變數換個指標名稱？
- **Falsifiability（可反駁性）**：未來是否存在可以證明此觀點錯誤或失效的證據？
- **Governance safety（治理安全性）**：它是否會偷渡新權重、新門檻、第七層、假精確或外部行動權限？

這些是驗證問題，不另長成 Phase / Wave / Work Order / Dashboard（階段／波次／工單／儀表板）。

新的永久知識仍必須完成必要驗證與使用者批准；本準則的存在不授權自動修改正式模型，也不改變任何既有治理鎖。
