# Operations

## Offline verification

```bash
./run_offline_tests.sh
./scripts/preflight_live_shadow.sh
```

## Windows（視窗作業系統）筆電上的 Observation History（歷史觀測）

營運 Runtime（執行環境）刻意放在 Git worktree（Git 工作樹）之外：

- Repository checkout（儲存庫檢出目錄）：`%USERPROFILE%\CRT_EvidenceRunner`
- Permanent runtime（永久執行環境）：`%USERPROFILE%\CRT_Runtime`
- Mobile L4 handoff（手機第四層交接檔）：`%USERPROFILE%\CRT_Runtime\incoming\l4\latest.json`
- Permanent Observation DB（永久觀測資料庫）：`%USERPROFILE%\CRT_Runtime\observations.sqlite3`
- Latest Evidence Pack（最新證據包）：`%USERPROFILE%\CRT_Runtime\evidence\latest.json`

手動執行一次 observation cycle（觀測循環）：

```powershell
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\run_observation_history_windows.ps1
```

### MSTR／ASST Market Health（市場健康度）→ GPT Wake（GPT 喚醒）

先以五份帶雜湊的來源證明產生 Market Health runtime artifacts（執行期施工件）：

```powershell
python -m crt_radar.mstr_asst_market_health_runtime `
  --input "$env:USERPROFILE\CRT_Runtime\market-health\runtime-input.json" `
  --full-day-output "$env:USERPROFILE\CRT_Runtime\market-health\full-day-market-intake.json" `
  --options-output "$env:USERPROFILE\CRT_Runtime\market-health\options-daily-snapshot.json" `
  --market-health-output "$env:USERPROFILE\CRT_Runtime\market-health\latest.json" `
  --manifest-output "$env:USERPROFILE\CRT_Runtime\market-health\manifest.json"
```

輸入必須完全符合 `CONFIG/MSTR_ASST_MARKET_HEALTH_SOURCE_V0.1.json`，且包含五個 `VALID`、hash 對齊、External Action Authority `NONE` 的來源證明。Commander lines 必須明示 `THREE_ARMY_COMMANDER` 與 `APPROVED`；`SIMULATION_ONLY` 或任何機器推測線一律 fail closed。所有計算先在記憶體內完成並驗證，之後才逐檔 atomic replace（原子置換）。

IBKR equity daily proof 可由唯讀 collector 產生：

```powershell
python -m crt_radar.ibkr_market_health_sources `
  --host 127.0.0.1 --port 7496 --client-id 761 `
  --equity-output "$env:USERPROFILE\CRT_Runtime\market-health\equity-daily-proof.json"
```

同一 collector 可產生 limited options coverage：underlying generic tick 100 提供 aggregate call／put volume；最近到期、近價合約只提供 covered OI／IV。單一合約 volume 若不可用，必須明示 `BLOCKED_NOT_AVAILABLE`，不得補零；coverage 也不得宣稱 full chain。

值班入口可選擇性讀取一份已驗證、local-only（僅本機）的
`CRT_MSTR_ASST_MARKET_HEALTH_V0.1` 快照：

```powershell
python -m crt_radar.daily_evidence_runner `
  --mstr-asst-market-health "$env:USERPROFILE\CRT_Runtime\market-health\latest.json" `
  --wake-output "$env:USERPROFILE\CRT_Runtime\wake\latest.json" `
  --notice-output "$env:USERPROFILE\CRT_Runtime\notifications\latest.json" `
  --handoff-output "$env:USERPROFILE\CRT_Runtime\gpt-handoff\latest.json" `
  --handoff-ledger "$env:USERPROFILE\CRT_Runtime\gpt-handoff\ledger.jsonl" `
  --bridge-outbox-dir "$env:USERPROFILE\CRT_Runtime\gpt-bridge-outbox"
```

Market Health 快照會先驗證 schema、內容一致性、雜湊與
External Action Authority（外部行動權限）`NONE`，才寫入 Evidence Pack
並參與 Wake Fusion。相同資產與相同語義事件由 GPT Handoff Ledger
（GPT 交接帳本）去重；不同資產的同名事件不會互相吞併。

此入口只形成本機 Evidence Pack、Wake、Notice、GPT Handoff 與 Bridge
Outbox。它不會 claim（領取）外部傳輸、不會通知使用者、不會修改持倉，
也不會下單。Wake（喚醒）不等於 Notification（通知）；是否值得通知仍由
GPT 依 Three-Army Commander Doctrine（三軍統帥準則）重新分析後裁決。

安裝 read-only recurring task（唯讀週期工作）。預設 cadence（執行頻率）為 60 分鐘，只屬於 Operational Default（營運預設值），不是 investment threshold（投資閾值）：

```powershell
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\install_observation_history_task_windows.ps1
```

如需不同 cadence（執行頻率），可明確傳入參數，例如 `-IntervalMinutes 30`。

Mobile L4 freshness guard（手機第四層新鮮度護欄）只能是 Transport Check（傳輸檢查）。它只檢查本機 handoff file modification time（交接檔修改時間），必要時輸出 `PHONE_L4_MISSING`、`PHONE_L4_STALE` 或 `PHONE_L4_CLOCK_SKEW`。預設 300 秒只屬於 Operational Default（營運預設值），不是 investment-model threshold（投資模型閾值）。它不得取代 Source Gate（資料來源閘門）對 source timestamp（來源時間戳）、schema（結構規格）、liquidation coverage（清算覆蓋率）與 evidence hash（證據雜湊）的驗證。

即使最終 Evidence Pack（證據包）因其他 critical family（關鍵資料族）維持 `BLOCKED`，個別 `VALID*`（有效狀態）觀測仍可用 idempotent write（冪等寫入）累積到永久 Observation DB（觀測資料庫）。只有 quality state（品質狀態）有效的 evidence row（證據列）可以成為歷史觀測；blocked（被阻擋）、stale（過期）、invalid（無效）、missing（缺失）或 transport-error（傳輸錯誤）證據都不得被提升進 Observation History（歷史觀測）。所有 critical blocker（關鍵阻擋）清除前，最終 Evidence Pack（證據包）必須維持 `BLOCKED`。

### Dollar proxy（美元代理）復原邊界

`DOLLAR_STRENGTH_PROXY` 維持現行 Source Registry（來源登錄表）的 Fail Closed（失敗即封鎖）政策。不得只為清除 `DOLLAR_STRENGTH_PROXY_STALE` 就放寬既有 10 天 freshness policy（新鮮度政策）。

若要替換目前核准的 Nominal Broad U.S. Dollar Index proxy（名目廣義美元指數代理），必須先取得 fresh（新鮮）、machine-readable（機器可讀）且 provenance-verifiable（可驗證溯源）的 Verified Source（已驗證來源），並明確接受其 semantics（語義）。在此之前，該資料族維持 `BLOCKED`；其他個別合格觀測可繼續累積。

## Required external Live Shadow

Use a persistent networked host with a persistent runtime volume:

```bash
CRT_RUNTIME_ROOT=/absolute/persistent/path ./scripts/run_live_shadow_24h.sh
CRT_RUNTIME_ROOT=/absolute/persistent/path ./scripts/verify_live_shadow.sh
```

The collector runs for 24 hours, performs one controlled restart around hour 12, archives every snapshot and appends a hash-chained Run Ledger.

## Acceptance

Only `live_shadow_summary.json` with decision `LIVE_SHADOW_PASS` may advance the system to P1-01 integration review. Any short run, corrupted archive, ledger mismatch, coverage below 0.95, blocked snapshot or missing restart remains `LIVE_SHADOW_NOT_YET_PASSED`.

## Authority

Read-only public market data only. No credentials, account connection, order placement, email, webhook or formal Radar scoring.
