# Windows 筆電執行手冊｜CRT Radar WIP

## 目標

在不使用 Codex 額度的情況下：

1. 離線重跑 88 項測試與安全檢查。
2. 將成果推到 GitHub 隔離分支，不碰 `main`。
3. 在筆電執行 24 小時唯讀 Live Shadow。

## 安全邊界

- 公開市場資料唯讀。
- 不連接券商、錢包或帳戶。
- 不下單、不寄信、不發 webhook。
- 分支名稱：`radar/integrated-wip-20260801`。
- PR 只能 Draft；不得 Merge。

## A. 安裝

1. 安裝 GitHub Desktop，登入 `qqc168-star`。
2. 安裝 Python 3.13，安裝時勾選 Add Python to PATH。
3. 在 GitHub Desktop Clone `qqc168-star/CRT_Master`。
4. 建立新分支 `radar/integrated-wip-20260801`。
5. 將交付 ZIP 解壓到 repository 根目錄。

## B. 初始化與測試

在 repository 根目錄開 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\run_offline_tests_windows.ps1
```

預期最後看到：

```text
SETUP_PASS
OFFLINE_TEST_PASS
```

## C. GitHub 保存

1. GitHub Desktop 檢查變更。
2. Commit message：`feat(radar): add integrated read-only WIP checkpoint`
3. Publish branch。
4. Preview Pull Request。
5. 建立 Draft PR，Base=`main`。
6. 不要 Merge。

## D. 24 小時 Live Shadow

先關閉睡眠、接上電源並保持網路：

```powershell
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\preflight_live_shadow_windows.ps1
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\start_live_shadow_24h_windows.ps1
```

狀態查詢：

```powershell
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\live_shadow_status_windows.ps1
```

24 小時後驗證：

```powershell
powershell -ExecutionPolicy Bypass -File .\radar\scripts\windows\verify_live_shadow_windows.ps1
```

只有 `LIVE_SHADOW_PASS` 才能進下一個 P1-01 Integration Review。
