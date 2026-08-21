# CRT STRC Q3→Q4 Rolling Strategy（STRC 第三季到第四季滾動策略）V0.2

```yaml
artifact_status: USER_APPROVED
strategy_status: ACTIVE_STRATEGY_HYPOTHESIS
formal_model_status: NON_FORMAL
overlay_type: ANALYST_STRATEGY_CONTEXT
supersedes: PRIOR_STRC_Q3Q4_STATIC_EXECUTION_HYPOTHESES
production: NOT_APPROVED
external_action_authority: NONE
action_output: NONE
approved_at: 2026-08-19
```

## 1. 定位

本文件是 STRC（微策略浮動股息優先股）專屬的使用者核准策略假說，供 CRT Evidence Pack（證據包）與 GPT（大廚）分析時讀取。

它不新增第七層、不改六層權重、不改燈號閾值、不改 BTC Season（比特幣季節）邏輯，也不產生自動 BUY／SELL（買入／賣出）指令。

`97 / 98.88 / 99–100` 與下列三段價位均屬 STRC strategy hypothesis（STRC 策略假說），不是 CRT formal threshold（CRT 正式門檻）。

## 2. Q3（第三季）賣出策略

三段式，最多三段：

| 段 | 比例 | 目標價 |
|---|---:|---:|
| 1 | 20% | 97.50 |
| 2 | 50% | 98.90 |
| 3 | 30% | 99.80 |

加權目標賣出價：

`0.20*97.50 + 0.50*98.90 + 0.30*99.80 = 98.89`

因此原 `98.88` 整體均價目標保留，不上修為 101／102，也不因短期波動任意下修。

## 3. Q4（第四季）回補策略

三段式，避免只等 80 美元而完全失去回補機會：

| 段 | 比例 | 最高回補價 |
|---|---:|---:|
| 1 | 20% | 86.00 |
| 2 | 30% | 83.00 |
| 3 | 50% | 80.00 |

加權最高回補價：

`0.20*86.00 + 0.30*83.00 + 0.50*80.00 = 82.10`

CRT 既有淨價差語義維持：

`G_net = S - B - D - C >= 10`

其中 `S` 為賣出價、`B` 為回補價、`D` 為離場期間股息機會成本、`C` 為交易摩擦。

## 4. Issuer Reflexivity（發行人反身性）每週驗收

每份 Strategy（微策略）週度 8-K（重大事項報告）後，必須更新：

- 本輪 STRC 回購金額、股數、平均回購價；
- 累計已使用與剩餘回購授權；
- 回購渠道與 execution window（執行窗口）；
- 同窗口可比市場成交量；只有渠道與範圍一致時才計算公司成交占比；
- disclosure window（揭露窗口）與 reaction window（市場反應窗口）；
- STRC 週內 OHLCV（開高低收成交量）；
- BTC（比特幣）買賣與 MSTR（微策略普通股）增發等資金來源；
- 公司降低干預後，市場價格是否仍能維持或上升。

禁止把 `1 - 公司成交占比` 解讀成「市場自主買盤比例」。

## 5. GPT（大廚）研究用 guideposts（觀察座標）

以下僅作滾動判斷，不升格為正式門檻：

- 公司單週回購降至約 `<= 90M USD`，而 STRC 仍能站上約 `97`：market handoff（市場接棒）證據增強。
- 公司單週仍投入約 `>= 100M USD`，但 STRC 仍長時間低於約 `96`：issuer-dependence warning（公司買盤依賴警訊）增強。
- 公司回購下降、STRC 仍維持 `97–99`：原 `98.88` 加權賣出目標可信度提高。
- 公司持續重買但價格走弱：不得把 `100` 視為必到；需重新評估第一段賣出比例與時間風險。

## 6. 時間尺度

管理層「9 月回到接近 100 美元面額」只作 reported policy statement（已報導政策陳述）與驗收時間窗，不作公司保證。

每次使用前必須重新核對最新官方來源與 supersession（取代狀態）。

## 7. Fail-closed（失敗關閉）

若最新 8-K、回購資料、成交量口徑或 reaction window（市場反應窗口）不足：

- affected judgment（受影響判斷）=`BLOCKED`
- `action_output = NONE`
- 不以舊週資料、估算量或新聞摘要補空缺。

## 8. 使用順序

`Six Layers（六層） -> Evidence Pack（證據包） -> Issuer Reflexivity（發行人反身性） -> Private Strategy Context（私人策略脈絡） -> GPT Judgment（GPT 判斷） -> User Decision（使用者決策）`

本策略不凌駕 CRT 六層主控；它只在主分析框架完成後，決定 STRC 的個人資本收割與回補節奏。
