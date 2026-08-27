# CRT Season × Three-Army Commander Deployment Doctrine V0.1（CRT 季節 × 三軍統帥部署準則 V0.1）

```yaml
artifact_status: USER_APPROVED
doctrine_status: NON_FORMAL
formal_model_status: NON_FORMAL
season_scope: STRATEGIC_RISK_POSTURE_ONLY
bull_foundation_scope: TRANSITION_CREDIBILITY_ONLY
commander_map_scope: TACTICAL_LINES_AND_CAPITAL_DEPLOYMENT
season_may_emit_trade_action: false
bull_foundation_may_emit_trade_action: false
formal_season_auto_update: false
production: NOT_APPROVED
external_action_authority: NONE
capital_decision_authority: USER_ONLY
action_output: NONE
```

## 1. 定位

本準則保存 Season（季節）、Bull Foundation（牛市地基）與 Three-Army Commander Map（三軍統帥地圖）的唯一分工，讓大週期判斷與具體資本決策不再互相越權。

它是 GPT（分析主廚）的非正式部署準則，不是新的正式模型、分數、權重、燈號、門檻、Season Router（季節路由器）、Evidence Pack（證據包）頂層區塊或自動交易系統。

核心分工只有三句：

1. Season（季節）只決定 strategic risk posture（戰略風險姿態）。
2. Bull Foundation（牛市地基）只判斷 bullish transition hypothesis（轉牛假說）的可信度。
3. Three-Army Commander Map（三軍統帥地圖）才負責具體攻擊線、第一防線、失效線、收割線與資本調度建議。

因此：

> 牛市裡可以撤退；熊轉牛時也可以進行有失效線的小規模戰術部署。Season（季節）不是交易按鈕。

## 2. 唯一權責鏈

| 構件 | 回答的問題 | 允許影響 | 禁止輸出 |
|---|---|---|---|
| Season（季節） | 現在的長週期環境適合偏攻、平衡、收割還是防守？ | 預設風險姿態、攻擊證據負擔、部位擴張意願、回踩容忍度與現金選擇權優先度 | 個別資產攻擊價、失效價、股數、`BUY / SELL`（買進／賣出） |
| Bull Foundation（牛市地基） | 轉牛證據是否從零散改善變成可持續、可接受且跨證據支持？ | 只更新轉牛假說的可信度，供統帥判讀 | 正式 Season（季節）、是否增援、燈號、資產排序、交易指令 |
| Three-Army Commander Map（三軍統帥地圖） | 現在這個資產在哪裡攻、守、退、收割，動用多少既有核准資本？ | 具體條件式資本建議與攻守閉環 | 自動成交、自動改持倉、自動改 Season（季節） |

執行順序：

`Latest evidence -> Formal Season or labeled analyst hypothesis + Bull Foundation transition credibility -> strategic risk posture + confidence context -> latest capital state -> Three-Army Commander Map -> GPT judgment -> User decision`

其中 Formal Season（正式季節）與 labeled analyst hypothesis（明確標示的分析假說）不得混稱。若 current `main`（目前主分支）的正式 Season Router（季節路由器）仍為 `BLOCKED / null`，GPT（分析主廚）只能寫「Season hypothesis（季節假說）」或「Weather（市場天氣）」，不得偽稱正式季節已確認，也不得用 Winter（冬季）偷偷代填缺失值。

當季節主張 `BLOCKED`（受阻）時，三軍統帥地圖仍可依獨立有效的價格結構、BTC（比特幣）傳導、發行人反身性、資本狀態與失效距離提出 claim-scoped（主張範圍限定）的 `WAIT / HOLD`（等待／續抱）或小規模戰術建議；這不構成 Season（季節）輸出。

## 3. 四季兵力姿態

四季是 deployment posture（部署姿態），不是四個切換日期，也不是取代正式九狀態語義的新路由器。下表中的「優先序」是新增風險資本與統帥注意力的預設順序，不是跨角色資產的永久報酬排名；實際配置仍須通過資產角色完整性、Relative Opportunity Cost（相對機會成本）、Shared Shock Propagation（共同衝擊傳播）與最新 Capital State（資本狀態）。

| 季節姿態 | 統帥任務與兵力姿態 | 資產角色優先序 | 新攻擊的證據負擔 | 撤退邏輯 |
|---|---|---|---|---|
| Winter（冬季） | 保存軍力、維持高流動性，只派可逆的小型偵察兵；不因跌幅大就把便宜當安全 | 現金選擇權與流動性 → 經驗證仍履行任務的收益／防守資產 → BTC（比特幣）核心偵察 → MSTR（Strategy 普通股）／ASST（Strive 普通股）高敏感度突擊 | 四季最高；不得只有價格穿越，需較多相對獨立的結構、現貨／成交品質、BTC（比特幣）傳導與發行人證據，且失效距離可承受 | 第一防線失守先凍結增援；失效線成立或發行人／資產角色惡化時優先縮風險，不用「季節快轉好」替戰術失敗辯護 |
| Spring（春季） | 建立橋頭堡，證據增加才漸進增援；容許在季節尚未完全確認時做有界戰術部署 | BTC（比特幣）結構橋頭堡 → 經驗證的 MSTR（Strategy 普通股）／ASST（Strive 普通股）選擇性突擊；同時保留現金後備，STRC（Strategy 永續優先股）／SATA（Strive 永續優先股）維持收益與防守任務 | 初期仍高；可隨 Acceptance（市場接受）、回踩承接、健康槓桿與 Bull Foundation（牛市地基）增強而逐步放寬，但不得降到只看漲價 | 戰術失效先撤該批兵；Bull Foundation（牛市地基）轉弱但防線仍在時先停止增援；不得因單一資產失敗自動宣布回到冬季 |
| Summer（夏季） | 讓趨勢工作，主力順勢持有，減少因短期震盪反覆下車 | BTC（比特幣）趨勢主軍 → 角色完整且反身性健康的 MSTR（Strategy 普通股）／ASST（Strive 普通股）進攻兵 → STRC（Strategy 永續優先股）／SATA（Strive 永續優先股）收益與組合平衡兵 → 戰術後備現金 | 相對春季降低，但最低品質不取消：仍要有資產條件、BTC（比特幣）條件、角色完整性與可接受的不對稱性；Season（季節）不能替代攻擊線 | 第一防線失守時重新驗收趨勢與角色；失效線成立即依計畫退出或縮減；即使正式牛季仍可對單一資產下 `SELL / WAIT`（賣出／等待）建議 |
| Autumn（秋季） | 收成果、縮戰線、恢復流動性；市場仍熱時先處理脆弱與高相關曝險 | 現金與流動性回收 → MSTR（Strategy 普通股）／ASST（Strive 普通股）高敏感度部位收割 → BTC（比特幣）核心風險重整 → 僅保留信用、流動性與角色仍完整的 STRC（Strategy 永續優先股）／SATA（Strive 永續優先股） | 對新增風險重新升高；對獲利保護、集中度下降與風險縮減所需證據負擔較低，但仍須寫明條件與代價 | 派發、反身性衰退、共同衝擊風險或第一防線失守時優先收割；失效線成立時加速撤退，不把收益型資產誤當現金或無風險防守 |

BTC（比特幣）在本準則中是 strategic anchor（戰略錨）與 transmission reference（傳導參考），不要求把它新增成現有盤前三軍統帥地圖的資產列。MSTR（Strategy 普通股）與 ASST（Strive 普通股）也不是永久進攻兵，STRC（Strategy 永續優先股）與 SATA（Strive 永續優先股）也不是永久防守兵；每次都要重新驗收 issuer reflexivity（發行人反身性）、資產角色與流動性。

## 4. Bull Foundation（牛市地基）只管理轉換可信度

Bull Foundation（牛市地基）沿用 GPT（分析主廚）的證據整合方法，觀察價格結構、真實需求、槓桿品質、回踩接受、持續性與跨層矛盾。它只回答：

> 「轉牛假說的地基正在形成、增強、惡化，還是證據不足？」

這些是 qualitative analyst descriptions（定性分析描述），不是新狀態機、分數或門檻。Bull Foundation（牛市地基）不得：

- 宣布正式 Spring（春季）或 Summer（夏季）。
- 因證據增加而自動調高燈號、部位或股數。
- 因證據減少而自動改 Season（季節）。
- 把同一底層價格衍生出的多個指標當成多票獨立證據。
- 越過 Decision Asymmetry Check（決策不對稱檢查）；確認增加但價格讓步過大時，三軍統帥仍可維持 `WAIT / HOLD`（等待／續抱）。

Bull Foundation（牛市地基）與三軍統帥地圖可以分歧：地基尚在形成，局部戰術攻擊仍可成立；地基已很強，單一資產的失效或估值／組合條件仍可要求撤退。

## 5. 三軍統帥地圖的戰術閉環

三軍統帥地圖必須先讀取最新 Evidence Pack（證據包）、Capital State（資本狀態）、未完成 Capital Plan（資本計畫）、Plan Drift（計畫偏離）與八個既有分析區塊，再形成以下人類可讀戰術語言：

| 戰術語言 | 現行閉環表面投影 | 用途 |
|---|---|---|
| 攻擊線 | `entry_condition` | 寫明資產價格條件、BTC（比特幣）價格條件與需要時的確認條件 |
| 第一防線 | `ACTION_MAP.analyst_judgment` 與 `exit_condition.stop_loss.confirmation_clause` | 定義回踩／守線後仍可維持論點的檢查點；失守先凍結增援與重新分析，不必等同完整失效 |
| 失效線 | `exit_condition.stop_loss` | 定義哪一組資產、BTC（比特幣）與確認條件會使原戰術論點失效 |
| 收割線 | `exit_condition.take_profit` | 定義獨立於停損通道的獲利收割條件 |
| 資本調度 | `entry_shares_delta` 與 `exit_shares_delta` | 表達建議增減股數；`0` 合法，停損與收割股數可不同 |

Season（季節）只能改變統帥使用這張地圖時的預設證據負擔、增援意願與風險容忍，不能直接生成、移動或取消任何一條具體價格線。

任何價格觸及都只是重新判讀條件，不是 machine trigger（機器觸發器）。GPT（分析主廚）負責條件式建議，使用者才有 Capital Decision Authority（資本決策權限）；機器不得自行成交、修改持倉、改寫既有批次狀態或移動資金。

## 6. 季節轉換的漸進式部署

轉換不是單點，部署也不得從空倉直接跳到滿額。下列順序是資本節奏語言，不是固定比例、新批次數或正式 gate（關卡）：

1. **Reserve（後備）**：保留現金選擇權，先定義可承受損失與失效線。
2. **Scout（偵察）**：三軍統帥地圖出現合格攻擊線時，只動用可逆、可由既有 Capital Plan（資本計畫）容納的最小戰術兵力。
3. **Bridgehead（橋頭堡）**：突破獲得 Acceptance（市場接受）或回踩守住第一防線後，才考慮建立可持續部位。
4. **Reinforcement（增援）**：相對獨立證據增加、Bull Foundation（牛市地基）增強、資產角色完整且 Decision Asymmetry（決策不對稱性）仍有利時，才考慮使用下一批既有核准資本。
5. **Trend hold / harvest（趨勢持有／收割）**：趨勢延續時讓贏家工作；第一防線、失效線、集中度或季節假說惡化時，依地圖凍結增援、收割或撤退。

較慢的 Season（季節）與 Bull Foundation（牛市地基）確認不是第一次買進的必要條件，也不是自動增援命令。較快的三軍統帥戰術成立時可先建立小型橋頭堡；後續慢證據只回答是否值得承擔更多風險。

## 7. 閉環反饋：戰術結果回饋假說，不改寫季節

每次戰術檢查後，GPT（分析主廚）應把結果回饋到下一次分析，但必須保持兩道防火牆：

1. **Asset-specific firewall（資產特定防火牆）**：單一資產成功或失敗，可能來自發行人、流動性、估值或執行位置，不能直接證明或推翻整體 Season（季節）。
2. **Formal Season firewall（正式季節防火牆）**：戰術結果只能成為下一輪 Evidence（證據）或 analyst confidence update（分析信心更新）；不得寫入、覆蓋或自動觸發正式 Season Router（季節路由器）。

反饋時只需回答四件事：

- 原攻擊條件是否被市場接受，第一防線是否守住。
- 成功／失敗主要是市場共同力量、BTC（比特幣）傳導，還是資產特定因素。
- 結果對目前 Season hypothesis（季節假說）與 Bull Foundation（牛市地基）是支持、反駁或仍不足判斷。
- 下一個會提高或降低信心的相對獨立證據是什麼。

獲利不自動等於假說正確，虧損也不自動等於季節錯誤。只有經過多次、跨資產角色、跨獨立證據家族且具有合理 BTC（比特幣）傳導的結果，才可調整非正式季節假說的信心；即使如此，正式 Season（季節）仍只能由獲批准且可執行的 formal router（正式路由器）產生。

## 8. 最小輸出格式

每次使用本準則時只新增以下五項到既有 GPT（分析主廚）分析，不另長出 Dashboard（儀表板）或第七層：

1. **Season source / posture（季節來源／姿態）**：正式輸出、明確標示的假說或 `BLOCKED`（受阻）；以及對應的戰略風險姿態。
2. **Bull Foundation credibility（牛市地基可信度）**：最重要的支持、反證與缺失證據。
3. **Commander action map（統帥行動地圖）**：每個資產的攻擊線、第一防線、失效線、收割線與資本調度建議。
4. **Closed-loop feedback（閉環反饋）**：上一輪戰術結果如何影響假說信心，並說明為何不構成自動 Season（季節）更新。
5. **Authority reminder（權限提醒）**：`action_output = NONE`、`capital_decision_authority = USER_ONLY`。

若所需證據不足，對受影響主張寫 `BLOCKED`（受阻），不得為填滿地圖而猜測價格線、股數、正式 mNAV（資產淨值倍數）或 Season（季節）。

## 9. 治理鎖

本準則不得且沒有：

- 新增第七層或修改 L1～L6（第一層至第六層）。
- 修改六層權重 `20 / 20 / 17 / 25 / 13 / 5`。
- 修改燈號門檻 `-60 / -35 / 35 / 60`。
- 修改未加限定的 `mNAV` 語義；它仍只指 `Diluted Equity mNAV`（稀釋後股權資產淨值倍數）。
- 修改、補完、繞過或執行 BTC Season formal router（比特幣正式季節路由器）。
- 修改 Production（正式生產）`NOT_APPROVED`。
- 修改 External Action Authority（外部行動權限）`NONE`。
- 修改 Capital Decision Authority（資本決策權限）`USER_ONLY`。
- 自動下單、存取帳戶、移動資金、認定成交或改寫私人 Capital State（資本狀態）。
- 修改 `radar/STATUS/CRT_ACTIVE_BATON.md` 的 `6 / 8 = 75%`、目前唯一進行中項目 `#7` 或下一個有效動作。

本文件的測試只能驗證文字中的權責分離、四季覆蓋、現行閉環欄位投影與治理鎖仍存在；測試通過不證明市場有效性、正式 Season（季節）有效性、Production（正式生產）就緒或任何交易績效。
