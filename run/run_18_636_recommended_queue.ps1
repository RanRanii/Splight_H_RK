param(
    [int]$WaitForPid = 0,
    [switch]$Execute,
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Continue"
$projectDir = Split-Path -Parent $PSScriptRoot
$queueName = "run_18_636_recommended_queue"
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

# Full 18-round rerun after adding ordinary outer key-schedule S-box
# activity to the truncated objective.  Previously successful results are
# intentionally rerun because they were generated with the old objective.
$tasks = @(
    @{ rank = 1;  group = "anchor-rm2"; r0 = 8; rm = 2; r1 = 8; reason = "18-round anchor under corrected objective" },
    @{ rank = 2;  group = "boundary";   r0 = 7; rm = 2; r1 = 9; reason = "known lower-long boundary case" },
    @{ rank = 3;  group = "boundary";   r0 = 9; rm = 2; r1 = 7; reason = "upper-long mirror boundary case" },
    @{ rank = 4;  group = "P1-rm3";     r0 = 8; rm = 3; r1 = 7; reason = "preferred upper-long rm=3 candidate" },
    @{ rank = 5;  group = "P1-rm3";     r0 = 7; rm = 3; r1 = 8; reason = "mirror rm=3 candidate" },
    @{ rank = 6;  group = "P2-rm4";     r0 = 8; rm = 4; r1 = 6; reason = "upper-long rm=4 candidate" },
    @{ rank = 7;  group = "P1-rm4";     r0 = 7; rm = 4; r1 = 7; reason = "balanced rm=4 candidate" },
    @{ rank = 8;  group = "P2-rm4";     r0 = 6; rm = 4; r1 = 8; reason = "lower-long rm=4 candidate" },
    @{ rank = 9;  group = "P3-rm5";     r0 = 8; rm = 5; r1 = 5; reason = "upper-long rm=5 candidate" },
    @{ rank = 10; group = "P3-rm5";     r0 = 7; rm = 5; r1 = 6; reason = "rm=5 directional candidate" },
    @{ rank = 11; group = "P3-rm5";     r0 = 6; rm = 5; r1 = 7; reason = "rm=5 mirror candidate" },
    @{ rank = 12; group = "P3-rm5";     r0 = 5; rm = 5; r1 = 8; reason = "lower-long rm=5 candidate" }
)

$singleMilpTimeLimitSec = 300
$globalTimeLimitSec = 1200
$exactVerifyTimeoutMs = 300000
$exactPathTimeoutSec = 1800

Write-QueueLog "PLAN START mode=$(if ($Execute) { 'EXECUTE' } else { 'PLAN_ONLY' }) weights=636 tasks=$($tasks.Count)"
Write-QueueLog "PARAMETERS tl=$singleMilpTimeLimitSec globalTl=$globalTimeLimitSec verifyMs=$exactVerifyTimeoutMs pathSec=$exactPathTimeoutSec rkMode=rk-ladder probtest=false"

foreach ($task in $tasks) {
    $caseName = "$($task.r0)-$($task.rm)-$($task.r1)_636"
    $status = if (Has-ResultDirectory $caseName) { Get-ExactResult $caseName } else { "ABSENT" }
    Write-QueueLog "PLAN rank=$($task.rank) group=$($task.group) case=$caseName current=$status reason='$($task.reason)'"
}

if (-not $Execute) {
    Write-QueueLog "PLAN ONLY: no search was started. Re-run with -Execute after review."
    exit 0
}

if ($WaitForPid -gt 0) {
    $waitingProcess = Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue
    if ($null -ne $waitingProcess) {
        Write-QueueLog "WAIT pid=$WaitForPid reason=avoid_parallel_gurobi_search"
        Wait-Process -Id $WaitForPid -ErrorAction SilentlyContinue
        Write-QueueLog "WAIT COMPLETE pid=$WaitForPid"
    } else {
        Write-QueueLog "WAIT SKIP pid=$WaitForPid reason=process_not_running"
    }
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
        Write-QueueLog "SKIP rank=$($task.rank) case=$caseName reason=EXACT_SUCCESS"
        $skipped += 1
        continue
    }

    if (Has-ResultDirectory $caseName) {
        Write-QueueLog "RETRY rank=$($task.rank) case=$caseName reason=INCOMPLETE_RESULT exact=$existingStatus"
    }

    $caseLogPath = Join-Path $caseLogDir "$caseName.log"
    $startedAt = Get-Date
    Write-QueueLog "START rank=$($task.rank) group=$($task.group) case=$caseName caseLog=$caseLogPath"

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
        Write-QueueLog "DONE rank=$($task.rank) case=$caseName exact=$exactResult exit=$exitCode elapsedSec=$elapsedSec"
        $completed += 1
        continue
    }

    Write-QueueLog "STOP rank=$($task.rank) case=$caseName exact=$exactResult exit=$exitCode elapsedSec=$elapsedSec"
    $failed += 1
    if ($StopOnFailure) {
        Write-QueueLog "QUEUE ABORTED reason=StopOnFailure case=$caseName"
        break
    }
}

Write-QueueLog "QUEUE COMPLETE completed=$completed skipped=$skipped failed=$failed"
if ($failed -gt 0) { exit 1 }
exit 0
