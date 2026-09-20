# Local Live Runtime（本機即時常駐執行）

## Scope（範圍）與施工基準

本次工作 F 於 2026-09-21 現場取得遠端 `main`：
`f46317bf61768de349052a6c76316675d59667e1`（含 #103、#104）。
#102 原始提交為 `f10e678f86fc335ebeadafdede37c4f98858141b`；#101 仍未合併。
在 `codex/work-f-local-live-rebase` 隔離工作樹，將最新主分支與 #102 已提交能力整合，
保留提交歷史，更新同一個 #102；不改寫原工作樹的未提交通知功能，也不使用暫存修改。
施工規劃：核對主分支與 #7 → 隔離整合 → 驗證共用擷取器相容性與完整回歸
→ 更新文件、提交、推送 #102，停在可審查狀態。

**合併／部署禁令：#7 真實無人值守傳輸驗收完成前，禁止合併 #102、啟用自動合併、
執行安裝器或更新實際常駐程序。離線測試通過不解除這項禁令。**
本次只完成工程整合，不執行安裝、排程更新、登出、斷線注入或供應端請求。

## Architecture（執行架構）

`Windows login -> Task Scheduler -> pythonw -> supervisor -> NativeIbkrFeed`

- Windows 工作排程器使用目前使用者互動登入、最低權限、單一執行個體、無執行時間上限。
  不需要 Windows 服務、Codex、開發環境或命令提示字元保持開啟。
- 穩定路徑 `%USERPROFILE%\CRT_LocalLiveRuntime`。安裝器複製程式到獨立版本目錄，
  使用穩定 Python 安裝的 `pythonw.exe`；排程動作不參照隔離工作樹。
  部署清單保存來源提交、未提交狀態與檔案雜湊。
- `radar/CONFIG/LOCAL_LIVE_RUNTIME_V0.1.json` 為本執行器唯一端點設定來源。
  其他工具原本的預設端點保持不變。
- 先偵測本機端點，再由獨立子程序呼叫既有 `NativeIbkrFeed.collect`。
  唯一擷取實作仍在 `ibkr_live_market_data_intake.py`；新增選用生命週期通知，
  未傳入通知者的擷取行為保持不變。
- 握手等待上限 12 秒；子程序心跳逾時 15 秒即終止。
  無端點、握手失敗、擷取失敗、子程序退出均清除本次狀態，進入 `WAITING_FOR_TWS`。
  退避為 5、10、20、40、60 秒並封頂，健康連線滿 60 秒才重設。
  每次擷取 300 秒後關閉並循環重連，限制記憶體使用；背景程序持續值班。
- 擷取器每秒檢查 TWS（交易工作站）連線；主管程序另有獨立期限。
  子程序發現主管消失即退出，不遺留行情連線。
- `data/pause.request` 關閉本執行器子程序與真實連線；移除後自動重新偵測。
  `data/stop.request` 為有序停止，重新啟動前须移除。
  控制不關閉 TWS，也不觸碰其餘客戶端。

## Journal / checkpoint（日誌／檢查點）

`data/lifecycle.sqlite3` 使用 SQLite WAL（預寫日誌）與同步持久化；
先提交事件，再以既有 `write_json_atomic` 原子更新 `data/checkpoint.json`。
保留 14 天事件，每小時清理到期紀錄；資料庫頁面重用。
紀錄實際行情型態、原始欄位、來源成交時間（若存在）與接收時間，兩種時間不互換。
每次變更僅保存最新一根五秒柱，避免重複保存整段歷史。

`RECEIVING` 僅表示本次連線收到即時模式回呼，不保證當下有新成交。
沒有新回呼仍可保有傳輸心跳；`exchange_trade_freshness=NOT_VALIDATED` 明確保留。
非即時資料不列入 `live_callback_assets`。失敗、重啟、暫停不沿用舊行情。
檢查點五秒後到期；過期狀態不得解讀為目前仍存活。

本執行器不輸出正式證據或指揮官計畫。永久維持：

```
action_output = NONE
external_action_authority = NONE
capital_decision_authority = USER_ONLY
machine_execution = FORBIDDEN
production = NOT_APPROVED
fail_closed = true
evidence_usable = false
```

不新增交易、部位、帳戶、資金或轉帳要求。不修改六層權重、燈號或 mNAV（市值淨資產比）語義。

## Operations（操作）

以下操作只適用於禁令解除且部署獲准後；本次未執行。

安裝與啟動（須已安裝官方 `ibapi` 與時區資料）：

```powershell
& .\radar\scripts\windows\install_local_live_runtime.ps1
```

實機驗收（TWS 已啟動且可回傳行情；不要求盤前成交）：

```powershell
& .\radar\scripts\windows\verify_local_live_runtime.ps1
```

驗收器確認本執行器的真實 TCP（傳輸控制協定）連線數為 `1 -> 0 -> 1`，
並終止已核對歸屬的擷取子程序，確認失敗關閉與自動恢復。它不停止 TWS。
報告寫入 `data/lifecycle-acceptance.json`。登入觸發設定由排程匯出核查；本次不登出使用者。

更新前建立停止檔，確認 `STOPPED` 及排程結束，移除停止檔，再重新安裝。
停用自動啟動可用 `Disable-ScheduledTask -TaskName CRT-Local-Live-Runtime`；
當下程序仍須使用停止檔有序結束。

## Dependency / pending（依賴／待驗收）

本生命週期工程不依賴 #101 未合併程式，可獨立審查；#101 仍须另外整合驗證。
最新主分支的 `gpt_transport_worker.py`、傳輸邊界、交接資料縮減、一次性驗收觀察器
及觀測啟動器原樣保留，沒有建立第二套傳輸工作程序、寄件匣或送達收據。
常駐主管只記錄行情傳輸，沒有把傳輸心跳冒充 #7 或 #8 端到端驗收。

#7 實際報告仍為 `WAITING_FOR_NEW_QUALIFIED_EVENT`，`generation_attempts=0`。
解除合併／部署禁令前，須取得新真實事件的 `PENDING -> CLAIMED -> DELIVERED`、
完成的供應端回應、綁定事件／資料包／請求／回應的有效送達收據，以及同事件不重送的證據。
不得因程式已合併、模型可連線或此處離線回歸通過而宣告 #7 完成。

`PENDING_MARKET_WINDOW`：盤前正式快照 → Work E 下游 → 指揮官觀察。
本執行器不自動宣告下游完成；正式串接仍須遵循合併後工程基準與原有驗真。
休市回傳前收盤欄位，只證明真實行情傳輸，不證明新成交或盤前驗收。

## Verification（驗證）

永久測試涵蓋端點缺失與有界退避、握手卡住、資料型態、連線中斷、
子程序退出／逾時、暫停恢復、重啟失效、單一程序鎖、持久日誌、
擷取器生命週期通知及原有唯讀要求集合。
驗收紀錄分開保存本次整合結果與原始 #102 歷史實機證據。
歷史傳輸／斷線／恢復通過不代表本次整合版本已部署，也不代表 #7 或 #8 完成。
