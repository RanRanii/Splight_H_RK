param(
    [int]$WaitForPid = 0
)

$ErrorActionPreference = "Continue"
$projectDir = Split-Path -Parent $PSScriptRoot
$logPath = Join-Path $projectDir "run\run_16_17_636_queue.log"

function Write-QueueLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    $line | Tee-Object -FilePath $logPath -Append
}

function Has-ExactSuccess([string]$CaseName) {
    $summaryPath = Join-Path $projectDir "results\$CaseName\exact_summary.json"
    if (-not (Test-Path $summaryPath)) { return $false }
    try {
        return ((Get-Content $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json).result -eq "SUCCESS")
    } catch {
        return $false
    }
}

if ($WaitForPid -gt 0) {
    Write-QueueLog "Waiting for active search PID $WaitForPid."
    Wait-Process -Id $WaitForPid -ErrorAction SilentlyContinue
}

$tasks = @(
    @{ r0 = 6; rm = 4; r1 = 6; tl = 600; global = 1200; verifyMs = 300000; pathSec = 3600 },
    @{ r0 = 9; rm = 4; r1 = 3; tl = 600; global = 1200; verifyMs = 300000; pathSec = 3600 },
    @{ r0 = 6; rm = 5; r1 = 5; tl = 600; global = 1200; verifyMs = 300000; pathSec = 3600 },
    @{ r0 = 8; rm = 5; r1 = 3; tl = 600; global = 1200; verifyMs = 300000; pathSec = 3600 },
    @{ r0 = 6; rm = 3; r1 = 8; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 10; rm = 3; r1 = 4; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 9; rm = 3; r1 = 5; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 6; rm = 4; r1 = 7; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 8; rm = 4; r1 = 5; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 9; rm = 4; r1 = 4; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 10; rm = 4; r1 = 3; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 6; rm = 5; r1 = 6; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 7; rm = 5; r1 = 5; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 8; rm = 5; r1 = 4; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 },
    @{ r0 = 9; rm = 5; r1 = 3; tl = 600; global = 1200; verifyMs = 600000; pathSec = 7200 }
)

Set-Location $projectDir
foreach ($task in $tasks) {
    $caseName = "$($task.r0)-$($task.rm)-$($task.r1)_636"
    if (Has-ExactSuccess $caseName) {
        Write-QueueLog "SKIP $caseName (existing Exact SUCCESS)."
        continue
    }

    Write-QueueLog "START $caseName"
    & python rkboom.py -r0 $task.r0 -rm $task.rm -r1 $task.r1 `
        -w0 6 -wm 3 -w1 6 `
        --tl $task.tl --global-tl $task.global `
        --rk-mode rk-ladder --exact-verify `
        --exact-verify-timeout-ms $task.verifyMs `
        --exact-path-timeout-sec $task.pathSec --probtest f
    $exitCode = $LASTEXITCODE
    if (Has-ExactSuccess $caseName) {
        Write-QueueLog "DONE $caseName (Exact SUCCESS, exit=$exitCode)."
    } else {
        Write-QueueLog "STOP $caseName (no Exact SUCCESS, exit=$exitCode)."
    }
}

Write-QueueLog "QUEUE COMPLETE"
