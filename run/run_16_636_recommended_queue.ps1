param(
    [int]$WaitForPid = 0,
    [switch]$Execute,
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Continue"
$projectDir = Split-Path -Parent $PSScriptRoot
$queueName = "run_16_636_recommended_queue"
$queueLogPath = Join-Path $PSScriptRoot "$queueName.log"
$caseLogDir = Join-Path $PSScriptRoot "logs\$queueName"
$targetTotalRounds = 16
$weightUpper = 6
$weightMiddle = 3
$weightLower = 6

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

# Re-run the remaining 16-round cases after the truncated objective was
# extended with outer key-schedule S-box activity.  The 8-2-6 anchor has
# already been re-run separately and is intentionally omitted here.
$tasks = @(
    @{ rank = 1;  phase = "P0"; r0 = 6; rm = 2; r1 = 8; wu = 6; wl = 8; outerExp = 56; maxCas = 3;  reason = "highest-value mirror check against completed 8-2-6 anchor" },
    @{ rank = 2;  phase = "P0"; r0 = 8; rm = 1; r1 = 7; wu = 8; wl = 6; outerExp = 56; maxCas = 3;  reason = "strong short-middle upper-long candidate" },
    @{ rank = 3;  phase = "P0"; r0 = 7; rm = 1; r1 = 8; wu = 6; wl = 8; outerExp = 56; maxCas = 3;  reason = "mirror of 8-1-7" },
    @{ rank = 4;  phase = "P0"; r0 = 7; rm = 2; r1 = 7; wu = 6; wl = 6; outerExp = 48; maxCas = 7;  reason = "symmetric short-middle baseline" },
    @{ rank = 5;  phase = "P1"; r0 = 5; rm = 3; r1 = 8; wu = 4; wl = 8; outerExp = 48; maxCas = 7;  reason = "remaining rm=3 candidate" },
    @{ rank = 6;  phase = "P1"; r0 = 4; rm = 4; r1 = 8; wu = 2; wl = 8; outerExp = 40; maxCas = 11; reason = "promising rm=4 candidate" },
    @{ rank = 7;  phase = "P2"; r0 = 5; rm = 4; r1 = 7; wu = 4; wl = 6; outerExp = 40; maxCas = 11; reason = "strict-baseline boundary check" },
    @{ rank = 8;  phase = "P3"; r0 = 5; rm = 5; r1 = 6; wu = 4; wl = 6; outerExp = 40; maxCas = 11; reason = "best prior rm=5 exploratory case" },
    @{ rank = 9;  phase = "P3"; r0 = 4; rm = 5; r1 = 7; wu = 2; wl = 6; outerExp = 32; maxCas = 15; reason = "second rm=5 exploratory case" },
    @{ rank = 10; phase = "P3"; r0 = 3; rm = 5; r1 = 8; wu = 2; wl = 8; outerExp = 40; maxCas = 11; reason = "lowest-priority rm=5 exploratory case" }
)

# This queue is exclusively for 16-round, 6/3/6 searches.  Reject an
# accidental non-16-round entry instead of silently executing it.
$invalidTasks = @(
    $tasks | Where-Object {
        ([int]$_.r0 + [int]$_.rm + [int]$_.r1) -ne $targetTotalRounds
    }
)
if ($invalidTasks.Count -gt 0) {
    $invalidCases = $invalidTasks | ForEach-Object { "$($_.r0)-$($_.rm)-$($_.r1)" }
    throw "Non-$targetTotalRounds-round task(s) in ${queueName}: $($invalidCases -join ', ')"
}

# Fixed search settings for this 16-round 636 campaign.
$singleMilpTimeLimitSec = 300
$globalTimeLimitSec = 1200
$exactVerifyTimeoutMs = 300000
$exactPathTimeoutSec = 1800

Write-QueueLog "PLAN START mode=$(if ($Execute) { 'EXECUTE' } else { 'PLAN_ONLY' }) totalRounds=$targetTotalRounds weights=$weightUpper/$weightMiddle/$weightLower tasks=$($tasks.Count)"
Write-QueueLog "PARAMETERS tl=$singleMilpTimeLimitSec globalTl=$globalTimeLimitSec verifyMs=$exactVerifyTimeoutMs pathSec=$exactPathTimeoutSec rkMode=rk-ladder probtest=false"

foreach ($task in $tasks) {
    $caseName = "$($task.r0)-$($task.rm)-$($task.r1)_636"
    $status = if (Has-ResultDirectory $caseName) { Get-ExactResult $caseName } else { "ABSENT" }
    Write-QueueLog (
        "PLAN rank=$($task.rank) phase=$($task.phase) case=$caseName " +
        "wu=$($task.wu) wl=$($task.wl) outerExp=$($task.outerExp) " +
        "maxCAS=$($task.maxCas) current=$status reason='$($task.reason)'"
    )
}

if (-not $Execute) {
    Write-QueueLog "PLAN ONLY: no search was started. Re-run with -Execute after review."
    exit 0
}

if ($WaitForPid -gt 0) {
    Write-QueueLog "WAIT pid=$WaitForPid"
    Wait-Process -Id $WaitForPid -ErrorAction SilentlyContinue
}

[System.IO.Directory]::CreateDirectory($caseLogDir) | Out-Null
Set-Location $projectDir

$completed = 0
$skipped = 0
$failed = 0

foreach ($task in $tasks) {
    $caseName = "$($task.r0)-$($task.rm)-$($task.r1)_636"
    if (Has-ResultDirectory $caseName) {
        $existingStatus = Get-ExactResult $caseName
        Write-QueueLog "SKIP case=$caseName reason=RESULT_DIRECTORY_EXISTS exact=$existingStatus"
        $skipped += 1
        continue
    }

    $caseLogPath = Join-Path $caseLogDir "$caseName.log"
    $startedAt = Get-Date
    Write-QueueLog "START rank=$($task.rank) phase=$($task.phase) case=$caseName caseLog=$caseLogPath"

    $childOutput = & python rkboom.py `
        -r0 $task.r0 -rm $task.rm -r1 $task.r1 `
        -w0 $weightUpper -wm $weightMiddle -w1 $weightLower `
        --tl $singleMilpTimeLimitSec `
        --global-tl $globalTimeLimitSec `
        --rk-mode rk-ladder `
        --exact-verify `
        --exact-verify-timeout-ms $exactVerifyTimeoutMs `
        --exact-path-timeout-sec $exactPathTimeoutSec `
        --probtest f 2>&1

    $exitCode = $LASTEXITCODE
    $childOutput | Out-File -FilePath $caseLogPath -Encoding UTF8
    $childOutput | Write-Output
    $elapsedSec = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
    $exactResult = Get-ExactResult $caseName

    if ($exitCode -eq 0 -and $exactResult -eq "SUCCESS") {
        Write-QueueLog "DONE case=$caseName exact=$exactResult exit=$exitCode elapsedSec=$elapsedSec"
        $completed += 1
        continue
    }

    Write-QueueLog "STOP case=$caseName exact=$exactResult exit=$exitCode elapsedSec=$elapsedSec"
    $failed += 1
    if ($StopOnFailure) {
        Write-QueueLog "QUEUE ABORTED reason=StopOnFailure case=$caseName"
        break
    }
}

Write-QueueLog "QUEUE COMPLETE completed=$completed skipped=$skipped failed=$failed"
if ($failed -gt 0) { exit 1 }
exit 0
