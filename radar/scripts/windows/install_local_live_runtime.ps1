param(
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..\..").Path,
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_LocalLiveRuntime",
    [string]$Python = (Get-Command python.exe).Source,
    [string]$TaskName = "CRT-Local-Live-Runtime"
)
$ErrorActionPreference = "Stop"
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
if ($RuntimeRoot -match '(?i)[\\/](\.worktrees|worktrees)[\\/]' -or $RuntimeRoot.StartsWith([IO.Path]::GetFullPath($RepoRoot), [StringComparison]::OrdinalIgnoreCase)) {
    throw "RuntimeRoot must be a stable directory outside the source checkout."
}
$Python = (Resolve-Path -LiteralPath $Python).Path
$Pythonw = Join-Path (Split-Path $Python) "pythonw.exe"
if (-not (Test-Path -LiteralPath $Pythonw)) { throw "A stable pythonw.exe installation is required." }
if ($Python -match '(?i)[\\/](\.worktrees|worktrees)[\\/]') { throw "Python cannot depend on a worktree." }
& $Python -c 'import ibapi, tzdata; from zoneinfo import ZoneInfo; ZoneInfo("America/New_York")'
if ($LASTEXITCODE -ne 0) { throw "Official ibapi and timezone data are required." }
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing -and $Existing.State -eq 'Running') { throw "Stop the existing runtime before deploying an update." }
$Release = Join-Path $RuntimeRoot ("releases\" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$Data = Join-Path $RuntimeRoot 'data'
New-Item -ItemType Directory -Path "$Release\src", $Data -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot 'radar\src\crt_radar') -Destination "$Release\src" -Recurse
Copy-Item -LiteralPath (Join-Path $RepoRoot 'radar\CONFIG\LOCAL_LIVE_RUNTIME_V0.1.json') -Destination "$Release\config.json"
$Bootstrap = @'
import multiprocessing
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
if __name__ == "__main__":
    multiprocessing.freeze_support()
    from crt_radar.local_live_runtime import main
    main()
'@
[IO.File]::WriteAllText((Join-Path $Release 'start_runtime.py'), $Bootstrap, [Text.UTF8Encoding]::new($false))
$SourceCommit = (& git -C $RepoRoot rev-parse HEAD)
$Manifest = [ordered]@{
    source_commit = $SourceCommit
    source_dirty = [bool](& git -C $RepoRoot status --porcelain --untracked-files=normal)
    deployed_at = (Get-Date).ToUniversalTime().ToString('o')
    python = $Pythonw
    release = $Release
    files = @(Get-ChildItem -LiteralPath $Release -Recurse -File | Where-Object Extension -ne '.pyc' | ForEach-Object {
        @{ path = $_.FullName.Substring($Release.Length + 1); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
}
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$Release\deployment.json" -Encoding UTF8
$Arguments = '"{0}" --config "{1}" --runtime-root "{2}"' -f "$Release\start_runtime.py", "$Release\config.json", $Data
$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument $Arguments -WorkingDirectory $Release
$User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal `
    -Settings $Settings -Description 'CRT local read-only market-data observation; no execution authority.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "CRT_RUNTIME_INSTALLED task=$TaskName release=$Release data=$Data"
