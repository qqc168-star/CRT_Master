$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "尚未建立 .venv。請先執行 setup_windows.ps1。" }
$Runtime = Join-Path $Root "runtime_live_shadow"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$env:PYTHONPATH = Join-Path $Root "src"
& $Python -m crt_radar.live_shadow_runner preflight `
  --registry (Join-Path $Root "CONFIG\SOURCE_REGISTRY_V1.2.json") `
  --policy (Join-Path $Root "CONFIG\LIVE_SHADOW_POLICY_V1.json") `
  --runtime-root $Runtime
if ($LASTEXITCODE -ne 0) { throw "PREFLIGHT_FAIL" }
