param(
    [switch]$Execute,
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Continue"
$projectDir = Split-Path -Parent $PSScriptRoot
$queueName = "run_19_636_concrete_then_rklb_queue"
$queueLogPath = Join-Path $PSScriptRoot "$queueName.log"
$caseLogDir = Join-Path $PSScriptRoot "logs\$queueName"

function Write-QueueLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Write-Output $line
    [System.IO.File]::AppendAllText(
        $queueLogPath,
        $line + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Get-ExactResult([string]$CaseName) {
    $summaryPath = Join-Path $projectDir "results\$CaseName\exact_summary.json"
    if (-not (Test-Path -LiteralPath $summaryPath)) { return "MISSING" }
    try {
        $summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $summary.result) { return "UNKNOWN" }
        return [string]$summary.result
    } catch {
        return "INVALID_SUMMARY"
    }
}

function Has-ResultDirectory([string]$CaseName) {
    $resultPath = Join-Path $projectDir "results\$CaseName"
    return Test-Path -LiteralPath $resultPath -PathType Container
}

# `order` is queue metadata only. It is not passed to rkboom.py.
# Phase 1: configurations extrapolated from successful concrete 18-round paths.
# Phase 2: configurations retained by the coarse RK-diff lower-bound table.
$tasks = @(
    @{ order = 1;  phase = "P1-concrete"; r0 = 8; rm = 2; r1 = 9;  reason = "combine 8-round upper weight 8 with 9-round lower weight 18" },
    @{ order = 2;  phase = "P1-concrete"; r0 = 8; rm = 1; r1 = 10; reason = "rm=1 zero-CAS candidate with strong 8-round upper path" },
    @{ order = 3;  phase = "P1-concrete"; r0 = 7; rm = 2; r1 = 10; reason = "extend successful 7-2-9 lower side by one round" },
    @{ order = 4;  phase = "P1-concrete"; r0 = 9; rm = 1; r1 = 9;  reason = "symmetric rm=1 zero-CAS exploration" },
    @{ order = 5;  phase = "P1-concrete"; r0 = 8; rm = 3; r1 = 8;  reason = "boundary case; needs lighter lower path or zero CAS" },
    @{ order = 6;  phase = "P1-concrete"; r0 = 9; rm = 2; r1 = 8;  reason = "reverse-direction check of 8-2-9" },
    @{ order = 7;  phase = "P2-rk-lb";   r0 = 7; rm = 4; r1 = 8;  outerLb = 56; maxCas = 3; reason = "passes RK-diff active-S-box lower-bound filter" },
    @{ order = 8;  phase = "P2-rk-lb";   r0 = 8; rm = 4; r1 = 7;  outerLb = 56; maxCas = 3; reason = "passes RK-diff active-S-box lower-bound filter" },
    @{ order = 9;  phase = "P2-rk-lb";   r0 = 6; rm = 5; r1 = 8;  outerLb = 56; maxCas = 3; reason = "passes RK-diff active-S-box lower-bound filter" },
    @{ order = 10; phase = "P2-rk-lb";   r0 = 7; rm = 5; r1 = 7;  outerLb = 48; maxCas = 7; reason = "largest coarse RK-diff lower-bound margin" },
    @{ order = 11; phase = "P2-rk-lb";   r0 = 8; rm = 5; r1 = 6;  outerLb = 56; maxCas = 3; reason = "passes RK-diff active-S-box lower-bound filter" }
)

$singleMilpTimeLimitSec = 300
$globalTimeLimitSec = 3600
$exactVerifyTimeoutMs = 600000
$exactPathTimeoutSec = 7200

Write-QueueLog "PLAN START mode=$(if ($Execute) { 'EXECUTE' } else { 'PLAN_ONLY' }) weights=636 tasks=$($tasks.Count)"
Write-QueueLog "PARAMETERS tl=$singleMilpTimeLimitSec globalTl=$globalTimeLimitSec verifyMs=$exactVerifyTimeoutMs pathSec=$exactPathTimeoutSec rkMode=rk-ladder probtest=false"

foreach ($task in $tasks) {
    $caseName = "$($task.r0)-$($task.rm)-$($task.r1)_636"
    $status = if (Has-ResultDirectory $caseName) { Get-ExactResult $caseName } else { "ABSENT" }
    $boundText = if ($task.phase -eq "P2-rk-lb") {
        " outerLb=$($task.outerLb) maxCAS=$($task.maxCas)"
    } else {
        ""
    }
    Write-QueueLog "PLAN order=$($task.order) phase=$($task.phase) case=$caseName current=$status$boundText reason='$($task.reason)'"
}

if (-not $Execute) {
    Write-QueueLog "PLAN ONLY: no search was started. Re-run with -Execute to launch the queue."
    exit 0
}

[System.IO.Directory]::CreateDirectory($caseLogDir) | Out-Null
Set-Location $projectDir

$completed = 0
$skipped = 0
$failed = 0

foreach ($task in $tasks) {
    $caseName = "$($task.r0)-$($task.rm)-$($task.r1)_636"
    $existingStatus = Get-ExactResult $caseName
    if ($existingStatus -eq "SUCCESS") {
        Write-QueueLog "SKIP order=$($task.order) case=$caseName reason=EXACT_SUCCESS"
        $skipped += 1
        continue
    }

    if (Has-ResultDirectory $caseName) {
        Write-QueueLog "RETRY order=$($task.order) case=$caseName reason=INCOMPLETE_RESULT exact=$existingStatus"
    }

    $caseLogPath = Join-Path $caseLogDir "$caseName.log"
    $startedAt = Get-Date
    Write-QueueLog "START order=$($task.order) phase=$($task.phase) case=$caseName caseLog=$caseLogPath"

    & python rkboom.py `
        -r0 $task.r0 -rm $task.rm -r1 $task.r1 `
        -w0 6 -wm 3 -w1 6 `
        --tl $singleMilpTimeLimitSec `
        --global-tl $globalTimeLimitSec `
        --rk-mode rk-ladder `
        --exact-verify `
        --exact-verify-timeout-ms $exactVerifyTimeoutMs `
        --exact-path-timeout-sec $exactPathTimeoutSec `
        --probtest f 2>&1 | Tee-Object -FilePath $caseLogPath

    $exitCode = $LASTEXITCODE
    $elapsedSec = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
    $exactResult = Get-ExactResult $caseName

    if ($exitCode -eq 0 -and $exactResult -eq "SUCCESS") {
        Write-QueueLog "DONE order=$($task.order) case=$caseName exact=$exactResult exit=$exitCode elapsedSec=$elapsedSec"
        $completed += 1
        continue
    }

    Write-QueueLog "STOP order=$($task.order) case=$caseName exact=$exactResult exit=$exitCode elapsedSec=$elapsedSec"
    $failed += 1
    if ($StopOnFailure) {
        Write-QueueLog "QUEUE ABORTED reason=StopOnFailure case=$caseName"
        break
    }
}

Write-QueueLog "QUEUE COMPLETE completed=$completed skipped=$skipped failed=$failed"
if ($failed -gt 0) { exit 1 }
exit 0
