param([string]$RuntimeRoot = "$env:USERPROFILE\CRT_LocalLiveRuntime", [int]$TimeoutSeconds = 60)
$ErrorActionPreference = 'Stop'
$Data = Join-Path $RuntimeRoot 'data'
$Checkpoint = Join-Path $Data 'checkpoint.json'
$Pause = Join-Path $Data 'pause.request'
if (Test-Path -LiteralPath $Pause) { throw 'Existing pause request must not be overridden.' }
function Wait-State([string]$State, [long]$After = 0) {
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-Path -LiteralPath $Checkpoint) {
            $Value = Get-Content -LiteralPath $Checkpoint -Raw | ConvertFrom-Json
            if ($Value.state -eq $State -and $Value.at_ms -gt $After -and
                $Value.valid_until_ms -gt [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) { return $Value }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $Deadline)
    throw "Timed out waiting for $State"
}
function Connections($Supervisor, $Port) {
    $Children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$Supervisor" | Select-Object -ExpandProperty ProcessId)
    @(Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | Where-Object {
        $_.RemotePort -eq $Port -and $_.OwningProcess -in $Children
    })
}
$Before = Wait-State 'RECEIVING'
$Port = [int]($Before.endpoint.Split(':')[-1])
$ConnectionsBefore = @(Connections $Before.pid $Port)
if ($ConnectionsBefore.Count -eq 0) { throw 'No real TWS socket owned by the runtime worker.' }
try {
    New-Item -ItemType File -Path $Pause | Out-Null
    $Paused = Wait-State 'PAUSED' $Before.at_ms
    $ConnectionsPaused = @(Connections $Before.pid $Port)
    if ($ConnectionsPaused.Count -ne 0 -or -not $Paused.fail_closed -or $Paused.evidence_usable) {
        throw 'Controlled disconnect failed to close the socket and evidence gate.'
    }
} finally {
    Remove-Item -LiteralPath $Pause -ErrorAction SilentlyContinue
}
$Resumed = Wait-State 'RECEIVING' $Paused.at_ms
$ConnectionsResumed = @(Connections $Resumed.pid $Port)
if ($ConnectionsResumed.Count -eq 0 -or $Resumed.pid -ne $Before.pid) { throw 'Runtime did not reconnect automatically.' }
# Fault injection targets only the proven CRT-owned child, never TWS.
$WorkerId = $ConnectionsResumed[0].OwningProcess
$Child = Get-CimInstance Win32_Process -Filter "ProcessId=$WorkerId"
if ($Child.ParentProcessId -ne $Resumed.pid) { throw 'Worker ownership changed; refusing fault injection.' }
Stop-Process -Id $WorkerId -Force
$FailedClosed = Wait-State 'WAITING_FOR_TWS' $Resumed.at_ms
if (-not $FailedClosed.fail_closed -or $FailedClosed.evidence_usable) { throw 'Worker loss did not fail closed.' }
$Recovered = Wait-State 'RECEIVING' $FailedClosed.at_ms
if (@(Connections $Recovered.pid $Port).Count -eq 0) { throw 'Worker crash did not recover a real socket.' }
$Report = [ordered]@{
    result = 'PASS'
    scope = 'REAL_TWS_TRANSPORT_CONTROLLED_DISCONNECT_RECONNECT'
    endpoint = $Before.endpoint
    before = $Before
    paused = $Paused
    resumed = $Resumed
    socket_counts = @($ConnectionsBefore.Count, $ConnectionsPaused.Count, $ConnectionsResumed.Count)
    worker_loss = $FailedClosed
    worker_recovery = $Recovered
    premarket_snapshot = 'PENDING_MARKET_WINDOW'
    work_e_downstream = 'PENDING_MARKET_WINDOW'
    commander_observation = 'PENDING_MARKET_WINDOW'
}
$Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Data 'lifecycle-acceptance.json') -Encoding UTF8
$Report | ConvertTo-Json -Depth 8
