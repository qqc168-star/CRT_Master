# CRT Liquidation Data Contract V1

## 原始事件

來源：Binance USDⓈ-M Futures `btcusdt@forceOrder` Market stream。

- `SELL` 強制平倉單：記為 `LONG liquidation`
- `BUY` 強制平倉單：記為 `SHORT liquidation`
- 美元名義金額：優先 `average price × accumulated filled quantity`，缺失時依序使用可驗證的成交／訂單欄位。
- 原始 payload 以 canonical JSON SHA-256 去重。
- 去重只影響計量；首次接收的正規化事件以 JSONL append-only 保存。

## 連線完整度

每次成功完成 WebSocket handshake 後才開始計入連線區間。Heartbeat 保存最後確認仍存活的時間；非正常中止後，重啟復原只計到最後 heartbeat，不得把停機缺口補成已連線。

`coverage_ratio = merged connected milliseconds / window milliseconds`

- 1h 與 24h 分別計算。
- Snapshot 頂層 coverage 取兩者最小值。
- 任一窗口 `< 0.95`：`BLOCKED`。
- 連線完整且無事件：合法 quiet window，金額可為 0。
- 有斷線缺口：不得以 0 清算冒充完整資料。

## Snapshot

Schema：`CRT_LIQ_AGGREGATE_SNAPSHOT_V1`

含：

- 1h／24h long、short、total liquidation USD
- event count
- coverage ratio／gap milliseconds
- as_of_ms
- event_set_hash／connection_set_hash／snapshot_hash
- quality_state／blocked_reasons

Source Gate 只有在 hash 驗證成功、quality state 合格、無 blocked reasons、freshness 合格時才接受。
