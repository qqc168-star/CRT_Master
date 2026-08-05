$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "尚未建立 .venv。請先執行 setup_windows.ps1。" }
$Runtime = Join-Path $Root "runtime_live_shadow"
$Logs = Join-Path $Runtime "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$PidFile = Join-Path $Runtime "live_shadow.pid"
if (Test-Path $PidFile) {
    $OldPid = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($OldPid -and (Get-Process -Id $OldPid -ErrorAction SilentlyContinue)) {
        throw "已有 Live Shadow 程序正在執行，PID=$OldPid"
    }
}
$env:PYTHONPATH = Join-Path $Root "src"
$Args = @(
    "-m", "crt_radar.live_shadow_runner", "collect",
    "--registry", (Join-Path $Root "CONFIG\SOURCE_REGISTRY_V1.2.json"),
    "--policy", (Join-Path $Root "CONFIG\LIVE_SHADOW_POLICY_V1.json"),
    "--runtime-root", $Runtime
)
$StdOut = Join-Path $Logs "live_shadow_stdout.log"
$StdErr = Join-Path $Logs "live_shadow_stderr.log"
$Proc = Start-Process -FilePath $Python -ArgumentList $Args -WorkingDirectory $Root `
    -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr -PassThru
Set-Content -Path $PidFile -Value $Proc.Id -Encoding ascii
Write-Host "LIVE_SHADOW_STARTED PID=$($Proc.Id)" -ForegroundColor Green
Write-Host "請保持筆電接電、網路連線，並關閉睡眠至少 24 小時。"
Write-Host "狀態查詢：powershell -ExecutionPolicy Bypass -File .\scripts\windows\live_shadow_status_windows.ps1"
