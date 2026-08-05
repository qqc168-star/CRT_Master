# WO-RADAR-MIG-002｜Persistent Liquidation Aggregator

## 目標

把 `btcusdt@forceOrder` 從短暫連線探針升級為可追溯、可計算資料完整度的持久化清算資料源。

## 必做

1. 常駐接收 Binance USD-M `/market` 的 `btcusdt@forceOrder`。
2. 原始事件 append-only 保存，使用事件雜湊去重。
3. 保存連線區間、斷線區間、重連次數與 coverage ratio。
4. 輸出 `CRT_LIQ_AGGREGATE_SNAPSHOT_V1`：
   - 1h／24h long liquidation USD
   - 1h／24h short liquidation USD
   - total liquidation USD
   - event count
   - coverage ratio
   - as_of_ms
5. coverage < 0.95、資料 stale、時鐘異常或快照損壞時 fail-closed。
6. 不得下單、不得登入、不得使用交易權限。

## 必測場景

- restart／reconnect
- duplicate event
- out-of-order event
- clock skew
- quiet window
- 斷線缺口不得補零
- 1h 與 24h 邊界計算
- 相同事件集重跑 hash 一致

## 驗收狀態

通過後僅能使 P1-01 到 `OFFLINE_E2E_PASS / READY_FOR_LIVE_SHADOW`；仍不得自行升格正式。
