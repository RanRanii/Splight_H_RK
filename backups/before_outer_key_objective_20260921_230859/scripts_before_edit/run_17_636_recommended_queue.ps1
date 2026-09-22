param(
    [switch]$Execute,
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Continue"
$projectDir = Split-Path -Parent $PSScriptRoot
$queueName = "run_17_636_recommended_queue"
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

# All cases satisfy r0 + rm + r1 = 17, rm <= 5, and
# 4 * (wu + wl) < 64. They were absent from results/ at launch.
$tasks = @(
    @{ rank = 1; r0 = 8; rm = 2; r1 = 7; wu = 8; wl = 6; outerExp = 56; maxCas = 3;  reason = "preferred short-middle direction" },
    @{ rank = 2; r0 = 7; rm = 2; r1 = 8; wu = 6; wl = 8; outerExp = 56; maxCas = 3;  reason = "mirror-direction check" },
    @{ rank = 3; r0 = 5; rm = 4; r1 = 8; wu = 4; wl = 8; outerExp = 48; maxCas = 7;  reason = "only untested eligible rm=4 case" },
    @{ rank = 4; r0 = 5; rm = 5; r1 = 7; wu = 4; wl = 6; outerExp = 40; maxCas = 11; reason = "balanced eligible rm=5 case" },
    @{ rank = 5; r0 = 4; rm = 5; r1 = 8; wu = 2; wl = 8; outerExp = 40; maxCas = 11; reason = "asymmetric eligible rm=5 case" }
)

# Keep the same 636 / rk-ladder / exact-verification settings used by the
# existing 17-round campaign so that the new results remain comparable.
$singleMilpTimeLimitSec = 600
$globalTimeLimitSec = 1200
$exactVerifyTimeoutMs = 600000
$exactPathTimeoutSec = 7200

Write-QueueLog "PLAN START mode=$(if ($Execute) { 'EXECUTE' } else { 'PLAN_ONLY' }) weights=636 tasks=$($tasks.Count)"
Write-QueueLog "PARAMETERS tl=$singleMilpTimeLimitSec globalTl=$globalTimeLimitSec verifyMs=$exactVerifyTimeoutMs pathSec=$exactPathTimeoutSec rkMode=rk-ladder probtest=false"

foreach ($task in $tasks) {
    $caseName = "$($task.r0)-$($task.rm)-$($task.r1)_636"
    $status = if (Has-ResultDirectory $caseName) { Get-ExactResult $caseName } else { "ABSENT" }
    Write-QueueLog (
        "PLAN rank=$($task.rank) case=$caseName wu=$($task.wu) wl=$($task.wl) " +
        "outerExp=$($task.outerExp) maxCAS=$($task.maxCas) current=$status reason='$($task.reason)'"
    )
}

if (-not $Execute) {
    Write-QueueLog "PLAN ONLY: no search was started. Re-run with -Execute after review."
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
        Write-QueueLog "SKIP case=$caseName reason=EXACT_SUCCESS exact=$existingStatus"
        $skipped += 1
        continue
    }

    if (Has-ResultDirectory $caseName) {
        Write-QueueLog "RETRY case=$caseName reason=INCOMPLETE_RESULT exact=$existingStatus"
    }

    $caseLogPath = Join-Path $caseLogDir "$caseName.log"
    $startedAt = Get-Date
    Write-QueueLog "START rank=$($task.rank) case=$caseName caseLog=$caseLogPath"

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
