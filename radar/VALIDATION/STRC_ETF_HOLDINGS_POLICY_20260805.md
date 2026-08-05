# CRT STRC ETF Radar V0.2 Candidate

## 已落地的拆分

1. Strategy／Strive 公司重大事件：每四小時檢查。
2. PFF、PFFA、PFXF ETF 持倉：停止每小時檢查。
3. ETF 主要檢查：美國交易日台北時間 08:30。
4. ETF 條件式重試：08:30 沒有新可用資料時，13:00 再試一次。
5. ETF 週趨勢：星期六台北時間 09:00。

## 資料來源層級

- StockAnalysis：三檔 ETF 廣域掃描。
- PFF：iShares／BlackRock 官方資料複核。
- PFFA：Virtus／InfraCap 官方資料複核。
- PFXF：VanEck 官方資料複核。

## BLOCKED_ALERT

只有以下情況成立：

- 超過兩個美國交易日仍沒有任何可用資料。
- STRC 無法與 STRF、STRK、STRD 區分。
- 官方與第三方在同一日期出現實質矛盾。
- 不同 as-of date 的資料被要求硬加總。

週末、美國休市日、合理的一個交易日公布延遲，不是資料故障。

## 治理邊界

- 正式 SSOT 仍為 CRT V1.10。
- Production 維持 NOT_APPROVED。
- 外部操作權限維持 NONE。
- 本分支只建立候選政策、程式判斷與回歸測試。
- 不修改正式權重、門檻或投資治理。
