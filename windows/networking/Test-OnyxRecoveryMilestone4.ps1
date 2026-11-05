# ONYX CORE v0.6.0 Milestone 4 validation. No production changes and no repair.
[CmdletBinding()]
param([switch]$ExerciseHistory)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Dev = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Collector = Join-Path $PSScriptRoot 'Collect-OnyxRecoveryEvidence.ps1'
$Engine = Join-Path $PSScriptRoot 'Evaluate-OnyxRecovery.py'
if ((Split-Path -Leaf $Dev) -ne 'onyx-core-v060' -or
    (& git -C $Dev branch --show-current) -ne 'feature/v0.6.0-reliability') {
    throw 'Refusing to test outside the v0.6.0 development worktree.'
}

$Tokens = $null
$ParseErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    $Collector, [ref]$Tokens, [ref]$ParseErrors
)
if (@($ParseErrors).Count -gt 0) {
    $ParseErrors | ForEach-Object { Write-Error $_.Message }
    throw 'Collector has PowerShell parse errors.'
}
Write-Host 'PASS: Collector PowerShell syntax'

& python $Engine --self-test
if ($LASTEXITCODE -ne 0) { throw 'Decision engine tests failed.' }
Write-Host 'PASS: Decision engine self-test'

$First = & $Collector
if ($First.repair_action -ne 'None' -or $First.decision.repair_action -ne 'None') {
    throw 'Unexpected repair authorization.'
}
if ($First.pi_error) { throw ('Live Pi diagnostic failed: ' + $First.pi_error) }
if ($First.history_error) { throw ('Live history persistence failed: ' + $First.history_error) }
if ($First.observation_count -lt 1 -or $First.observation_count -gt 12) {
    throw 'Observation count is out of range.'
}
if (-not (Test-Path -LiteralPath $First.history_path -PathType Leaf)) {
    throw 'Collector failed to create persistent history.'
}
Write-Host ('PASS: Live read-only collector (decision={0}; observations={1})' -f
    $First.decision.decision, $First.observation_count)

if ($ExerciseHistory) {
    # Use a throwaway file to test retention and corruption without touching real history.
    $TestRoot = Join-Path $env:TEMP ('OnyxCore-v060-m4-' + [guid]::NewGuid().ToString('N'))
    $TestHistory = Join-Path $TestRoot 'recovery-observations.json'
    try {
        $null = New-Item -ItemType Directory -Path $TestRoot -Force
        $OldTime = [DateTimeOffset]::UtcNow.AddMinutes(-10).ToString('o')
        @{
            schema_version = 1
            observations = @(@{
                timestamp_utc = $OldTime
                windows = @{ classification = 'WindowsPathReady' }
                pi = @{ classification = 'PiInternetVerified'; gateway_reachable = $true }
                windows_upstream_ok = $true
                external_tcp_failed_targets = @()
            })
        } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $TestHistory -Encoding UTF8
        $A = & $Collector -HistoryPath $TestHistory
        if ($A.history_error) { throw ('Stale-history replacement failed: ' + $A.history_error) }
        if ($A.pi_error) { throw ('Pi diagnostic failed: ' + $A.pi_error) }
        if ($A.observation_count -ne 1) { throw 'Stale history was not pruned.' }
        Write-Host 'PASS: Stale history was pruned and persisted'
        $B = & $Collector -HistoryPath $TestHistory
        if ($B.history_error) { throw ('Second history replacement failed: ' + $B.history_error) }
        if ($B.pi_error) { throw ('Pi diagnostic failed: ' + $B.pi_error) }
        if ($B.observation_count -ne 2) { throw 'Fresh observations were not persisted.' }
        $DiskHistory = Get-Content -LiteralPath $TestHistory -Raw -Encoding UTF8 | ConvertFrom-Json
        if (@($DiskHistory.observations).Count -ne 2) {
            throw 'Persisted history does not contain two observations.'
        }
        Write-Host 'PASS: Two invocations retained two persisted observations'
        [IO.File]::WriteAllText($TestHistory, '{invalid JSON')
        $C = & $Collector -HistoryPath $TestHistory
        if ($C.observation_count -ne 1 -or $C.decision.decision -ne 'Investigate' -or
            -not $C.history_error) {
            throw 'Corrupt history was not reset with fail-closed decision.'
        }
        if ($C.pi_error) { throw ('Pi diagnostic failed: ' + $C.pi_error) }
        $ResetDiskHistory = Get-Content -LiteralPath $TestHistory -Raw -Encoding UTF8 | ConvertFrom-Json
        if (@($ResetDiskHistory.observations).Count -ne 1) {
            throw 'Corrupt history was not replaced with a clean single observation.'
        }
        Write-Host 'PASS: Corrupt history reset and decision failed closed'
        $D = & $Collector -HistoryPath $TestHistory
        if ($D.history_error) { throw ('Recovery after history reset failed: ' + $D.history_error) }
        if ($D.pi_error) { throw ('Pi diagnostic failed: ' + $D.pi_error) }
        if ($D.observation_count -ne 2) {
            throw 'History did not resume normal persistence after reset.'
        }
        Write-Host 'PASS: History resumes persistence after reset'
    }
    finally { Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
Write-Host 'PASS: Milestone 4 validation completed without repair actions'
