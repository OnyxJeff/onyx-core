# ONYX CORE v0.6.0 - Milestone 6 release-readiness verification.
# Default is offline and read-only. Opt-in switches run existing tests / read-only HTTP probes.
[CmdletBinding()]
param(
    [switch]$RunBaselineTests,
    [switch]$LiveReadOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Dev = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Prod = 'D:\github_repos\onyx-core'
$ExpectedDevBranch = 'feature/v0.6.0-reliability'
$ExpectedProdHead = '6d1e599'
$RequiredMilestone = '725ed95'
$RequiredFiles = @(
    'windows\networking\Evaluate-OnyxRecovery.py',
    'windows\networking\Collect-OnyxRecoveryEvidence.ps1',
    'windows\networking\Test-OnyxRecoveryMilestone4.ps1',
    'windows\networking\Test-OnyxRecoveryMilestone5.ps1',
    'windows\networking\Test-OnyxRecoveryMilestone5.py',
    'windows\networking\Test-OnyxRecoveryMilestone6.ps1',
    'windows\networking\Test-OnyxUsbIcsReadiness.ps1',
    'pi\scripts\Test-OnyxUsbForwarding.py',
    'docs\v0.6.0\RELEASE_READINESS.md',
    'docs\v0.6.0\OPERATIONS.md',
    'docs\v0.6.0\DEPLOYMENT_ROLLBACK.md'
)

function Assert-OnyxM6 {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw ('FAIL: ' + $Message) }
}

function Invoke-OnyxNative {
    param([string]$Label, [scriptblock]$Command)
    Write-Host ('--- ' + $Label)
    & $Command
    $Exit = $LASTEXITCODE
    Assert-OnyxM6 ($Exit -eq 0) ("$Label exited with code $Exit")
    Write-Host ('PASS: ' + $Label)
}

Write-Host "`n=== Milestone 6: repository guard ==="
Assert-OnyxM6 ((Split-Path -Leaf $Dev) -eq 'onyx-core-v060') 'Wrong development worktree'
Assert-OnyxM6 (Test-Path -LiteralPath $Prod -PathType Container) 'Production repository path missing'
$DevBranch = & git -C $Dev branch --show-current
Assert-OnyxM6 (($LASTEXITCODE -eq 0) -and ($DevBranch -eq $ExpectedDevBranch)) 'Wrong development branch'
$ProdBranch = & git -C $Prod branch --show-current
Assert-OnyxM6 (($LASTEXITCODE -eq 0) -and ($ProdBranch -eq 'main')) 'Production branch changed'
$ProdHead = & git -C $Prod rev-parse --short=7 HEAD
Assert-OnyxM6 (($LASTEXITCODE -eq 0) -and ($ProdHead -eq $ExpectedProdHead)) 'Production HEAD changed'
& git -C $Dev merge-base --is-ancestor $RequiredMilestone HEAD
Assert-OnyxM6 ($LASTEXITCODE -eq 0) 'Milestone 5 is not an ancestor of development HEAD'
& git -C $Dev merge-base --is-ancestor $ExpectedProdHead HEAD
Assert-OnyxM6 ($LASTEXITCODE -eq 0) 'Production baseline is not an ancestor of development HEAD'

$ProductionStatus = @(& git -C $Prod status --porcelain -uall)
Assert-OnyxM6 ($LASTEXITCODE -eq 0) 'Could not inspect production status'
$UnexpectedProd = @($ProductionStatus | Where-Object {
    $_ -ne '?? windows/collector/Send-OnyxTelemetry.pre-v050.bak'
})
Assert-OnyxM6 ($UnexpectedProd.Count -eq 0) (
    'Unexpected production worktree changes: ' + ($UnexpectedProd -join '; ')
)
Write-Host 'PASS: Development ancestry, production branch/HEAD and known backup are guarded'

Write-Host "`n=== Milestone 6: scope audit against production baseline ==="
$Changed = @(& git -C $Dev diff --name-only "${ExpectedProdHead}..HEAD")
Assert-OnyxM6 ($LASTEXITCODE -eq 0) 'Unable to diff baseline against branch'
$Changed += @(& git -C $Dev diff --name-only)
Assert-OnyxM6 ($LASTEXITCODE -eq 0) 'Unable to inspect unstaged changes'
$Changed += @(& git -C $Dev diff --cached --name-only)
Assert-OnyxM6 ($LASTEXITCODE -eq 0) 'Unable to inspect staged changes'
$Changed += @(& git -C $Dev ls-files --others --exclude-standard)
Assert-OnyxM6 ($LASTEXITCODE -eq 0) 'Unable to inspect untracked files'
$Changed = @($Changed | Where-Object { $_ } | Sort-Object -Unique)
Assert-OnyxM6 ($Changed.Count -gt 0) 'No development changes were found'
foreach ($Relative in $Changed) {
    $Allowed = (
        $Relative -like 'windows/networking/*' -or
        $Relative -eq 'pi/scripts/Test-OnyxUsbForwarding.py' -or
        $Relative -like 'docs/v0.6.0/*' -or
        $Relative -eq 'docs/reliability/recovery-policy-v0.6.0.md'
    )
    Assert-OnyxM6 $Allowed ("Out-of-scope change relative to v0.5.1: " + $Relative)
}
Write-Host ('PASS: {0} changed files are inside v0.6.0 diagnostic/test/docs scope' -f $Changed.Count)
Write-Host 'PASS: Existing receiver, gateway, overlays and telemetry collector are outside the diff'

Write-Host "`n=== Milestone 6: required files and policy controls ==="
foreach ($Relative in $RequiredFiles) {
    Assert-OnyxM6 (Test-Path -LiteralPath (Join-Path $Dev $Relative) -PathType Leaf) ("Missing file: " + $Relative)
}
$CollectorText = [IO.File]::ReadAllText((Join-Path $Dev 'windows\networking\Collect-OnyxRecoveryEvidence.ps1'))
$EngineText = [IO.File]::ReadAllText((Join-Path $Dev 'windows\networking\Evaluate-OnyxRecovery.py'))
Assert-OnyxM6 ($CollectorText.Contains('OnyxCore-v060-Development')) 'Collector no longer defaults to isolated development history'
Assert-OnyxM6 ($CollectorText.Contains('BatchMode=yes')) 'Collector lost noninteractive SSH requirement'
Assert-OnyxM6 ($CollectorText.Contains('StrictHostKeyChecking=yes')) 'Collector lost SSH host-key verification'
Assert-OnyxM6 ($CollectorText.Contains('dns_resolves') -and $CollectorText.Contains('https_works')) 'Pi evidence fields missing from collector'
Assert-OnyxM6 ($CollectorText.Contains("repair_action = 'None'")) 'Collector dry-run output guard missing'
Assert-OnyxM6 ($EngineText.Contains('"repair_action": "None"')) 'Decision engine dry-run output guard missing'
Write-Host 'PASS: Development-only state, noninteractive SSH and no-repair output guards remain present'

Write-Host "`n=== Milestone 6: existing offline reliability regressions ==="
Invoke-OnyxNative 'Decision engine self-test' {
    & python (Join-Path $Dev 'windows\networking\Evaluate-OnyxRecovery.py') --self-test
}
Invoke-OnyxNative 'Pi forwarding self-test (no network)' {
    & python (Join-Path $Dev 'pi\scripts\Test-OnyxUsbForwarding.py') --self-test
}

# Milestone 5 runs Python scenarios and mocked SSH/history helpers without a live collector.
$Milestone5 = Join-Path $Dev 'windows\networking\Test-OnyxRecoveryMilestone5.ps1'
& $Milestone5
Assert-OnyxM6 ($?) 'Milestone 5 test runner did not succeed'
Write-Host 'PASS: Milestone 5 offline reliability suite'

if ($RunBaselineTests) {
    Write-Host "`n=== Milestone 6: opted-in v0.5.1 regression suites ==="
    Invoke-OnyxNative 'Receiver unit tests' {
        Push-Location -LiteralPath $Dev
        try { & python -m unittest discover -s tests/services -p 'test_*.py' -v }
        finally { Pop-Location }
    }
    Invoke-OnyxNative 'Gateway regression tests' {
        & python (Join-Path $Dev 'windows\gateway\Test-OnyxGateway.py')
    }
    Invoke-OnyxNative 'CPU-temperature integration tests' {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `
            (Join-Path $Dev 'windows\collector\Test-OnyxCpuTemperature.ps1')
    }
}

if ($LiveReadOnly) {
    Write-Host "`n=== Milestone 6: opted-in live read-only checks ==="
    # Previous milestone validates the collector with a temporary history file.
    $M4Test = Join-Path $Dev 'windows\networking\Test-OnyxRecoveryMilestone4.ps1'
    & $M4Test -ExerciseHistory
    Assert-OnyxM6 ($?) 'Milestone 4 live read-only validation failed'
    Write-Host 'PASS: Live diagnostic and temporary-history tests'

    foreach ($Route in @('/dashboard', '/overlay', '/overlay-portrait')) {
        $Url = 'http://127.0.0.1:18766' + $Route
        $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop
        Assert-OnyxM6 ($Response.StatusCode -eq 200) ("Gateway HTTP status invalid: " + $Route)
        Write-Host ('PASS: Gateway returned HTTP 200 for ' + $Route)
    }
    Write-Host 'NOTE: HTTP 200 does not establish rendered overlays or telemetry freshness.'
}

Write-Host "`nPASS: Milestone 6 selected validations completed. No repair/deployment actions."
if (-not $RunBaselineTests) { Write-Host 'PENDING: Run -RunBaselineTests before release approval.' }
if (-not $LiveReadOnly) { Write-Host 'PENDING: Run -LiveReadOnly and manually inspect OBS overlays before release approval.' }
