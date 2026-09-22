# Local Live Runtime（本機即時常駐執行）

## Scope（範圍）與施工基準

本次從現場確認的最新 main `8249f927fd1ad0586f9ce92e741ea6a062f18ccc` 建立新的隔離工作樹，
合併 PR #102 已提交 head `d0b641a9d9c5dcd65f6933bba1cd7baa85a52fda`，保留歷史。
只補回既有 Local Live Runtime 能力；舊工作樹及 stash untouched。

#7 remains COMPLETE，7 / 8 = 87.5%。#105～#108 的 payload closure、live receipt、
單次 acceptance override、下一循環回到正式 90/95，以及 16 KiB ceiling 均保持最新 main 行為。
既有 receipt hash：`3c3c29a492e7a3cf59a2650bebf97c484383dc36cba78994948371f66f368a8b`。
本次已獲使用者授權：離線回歸及 CI 全過後合併、部署並實機驗收；不重做 #7，不開始 #8。

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

以下操作在本次回歸、CI 通過及 PR 合併後執行。部署結果另行記錄，不以歷史驗收代替。

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

#7 已完成，既有 durable receipt 與 replay 去重證據保持不變；本次不新增驗收用 GPT 請求。

`PENDING_MARKET_WINDOW`：盤前正式快照 → Work E 下游 → 指揮官觀察。
本執行器不自動宣告下游完成；正式串接仍須遵循合併後工程基準與原有驗真。
休市回傳前收盤欄位，只證明真實行情傳輸，不證明新成交或盤前驗收。

## Verification（驗證）

永久測試涵蓋端點缺失與有界退避、握手卡住、資料型態、連線中斷、
子程序退出／逾時、暫停恢復、重啟失效、單一程序鎖、持久日誌、
擷取器生命週期通知及原有唯讀要求集合。
驗收紀錄分開保存本次整合結果與原始 #102 歷史實機證據。
歷史傳輸／斷線／恢復通過不代表本次整合版本已部署，也不代表 #7 或 #8 完成。

本次離線驗證：完整 831 項通過；compileall、program registry、read-only surface、三支 PowerShell parser 通過。

## 2026-09-22 部署與驗收

PR #102 已合併：`0fc2f9ba108ac4077961a32dcf4e80e2822a0cda`。兩項 CI 通過。
真正值班 checkout 與安裝來源均對齊此合併 SHA，manifest source_dirty=false，全部部署檔案雜湊一致。
登入觸發及 pythonw 主管存活通過；實際 TCP 1 → 0 → 1、pause、子程序故障失敗關閉與恢復均通過。
stop.request 已有序退出；排程初次輪詢逾時後確認 Ready，舊程序消失，過期 checkpoint 由新程序取代。
SQLite quick_check=ok；現場一個主管、一個行情子程序、一條 TWS 連線，無第二套 GPT transport worker。
握手失敗禁止訂閱、訂閱失敗清理由離線測試覆蓋，未對 TWS 注入這兩種錯誤；未執行 Windows 登出登入。
初次實機驗收時 TWS 不在執行，正確等待並失敗關閉；TWS 恢復後完整重連驗收通過。
#7 原始 durable receipt 已重新計算確認綁定，沒有重新傳送或重做 #7。
詳見 `LOCAL_LIVE_RUNTIME_ACCEPTANCE_V0.1.json` 的 deployment_acceptance；#8 未開始。
