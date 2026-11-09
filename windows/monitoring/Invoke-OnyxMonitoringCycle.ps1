# ONYX CORE v0.7.0 - Milestone 1: one manually authorized, read-only cycle.
# Development-only entry point. No scheduler, incident writer, or network repair.
[CmdletBinding()]
param(
    [switch]$LiveReadOnly,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-OnyxCycleSummary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][object]$Report,
        [Parameter(Mandatory=$true)][DateTimeOffset]$StartedAt,
        [Parameter(Mandatory=$true)][DateTimeOffset]$FinishedAt,
        [Parameter(Mandatory=$true)][string]$ExpectedHistoryPath
    )

    # Validate an actual completed collector result; never manufacture healthy evidence.
    if ($null -eq $Report -or $Report -is [array] -or
        $Report.mode -ne 'ReadOnlyPersistentHistory') {
        throw 'Collector returned an invalid evidence mode.'
    }
    if ($Report.repair_action -ne 'None' -or
        $null -eq $Report.decision -or $Report.decision.repair_action -ne 'None') {
        throw 'Collector returned a prohibited or invalid repair action.'
    }
    if (-not [string]::Equals([string]$Report.history_path, $ExpectedHistoryPath,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Collector reported an unapproved history path.'
    }
    if ($null -eq $Report.observation -or
        $null -eq $Report.observation.windows -or
        $null -eq $Report.observation.pi -or
        [string]::IsNullOrWhiteSpace([string]$Report.observation.windows.classification) -or
        [string]::IsNullOrWhiteSpace([string]$Report.observation.pi.classification)) {
        throw 'Collector returned incomplete Windows/Pi evidence.'
    }
    $Allowed = @('Healthy', 'WaitAndRetry', 'Investigate', 'PossibleIcsFailure')
    $Decision = [string]$Report.decision.decision
    if ($Decision -notin $Allowed) {
        throw 'Collector returned an unknown decision classification.'
    }
    $Count = 0
    if (-not [int]::TryParse([string]$Report.observation_count, [ref]$Count) -or
        $Count -lt 1 -or $Count -gt 12) {
        throw 'Collector returned an invalid observation count.'
    }
    $Suspected = 0
    if (-not [int]::TryParse([string]$Report.decision.consecutive_suspected, [ref]$Suspected) -or
        $Suspected -lt 0 -or $Suspected -gt 12) {
        throw 'Collector returned an invalid suspected-failure count.'
    }
    if ($FinishedAt -lt $StartedAt) {
        throw 'Invalid cycle timestamps.'
    }

    $HistoryError = -not [string]::IsNullOrWhiteSpace([string]$Report.history_error)
    $WindowsError = -not [string]::IsNullOrWhiteSpace([string]$Report.windows_error)
    $PiError = -not [string]::IsNullOrWhiteSpace([string]$Report.pi_error)
    $Partial = $HistoryError -or $WindowsError -or $PiError
    if ($Partial -and $Decision -ne 'Investigate') {
        throw 'Contradictory decision: incomplete evidence must not be marked healthy.'
    }
    if ($Decision -eq 'Healthy' -and
        ($Report.observation.windows.classification -ne 'WindowsPathReady' -or
         $Report.observation.pi.classification -ne 'PiInternetVerified' -or
         $Report.observation.windows_upstream_ok -ne $true)) {
        throw 'Contradictory healthy decision and source evidence.'
    }
    # Suppress detailed probe errors and paths from the structured summary.
    # Those stay in local development history and the existing diagnostic report.
    [PSCustomObject]@{
        schema_version        = 1
        source                = 'LiveRestrictedDiagnostic'
        cycle_started_utc     = $StartedAt.ToString('o')
        cycle_finished_utc    = $FinishedAt.ToString('o')
        duration_ms           = [int64][Math]::Round(($FinishedAt - $StartedAt).TotalMilliseconds)
        cycle_status          = $(if ($Partial) { 'EvidenceIncomplete' } else { 'Complete' })
        connectivity_decision = $Decision
        decision_reason       = [string]$Report.decision.reason
        windows_classification = [string]$Report.observation.windows.classification
        pi_classification      = [string]$Report.observation.pi.classification
        observation_count      = $Count
        consecutive_suspected  = $Suspected
        history_error_present  = [bool]$HistoryError
        windows_error_present  = [bool]$WindowsError
        pi_error_present       = [bool]$PiError
        repair_action          = 'None'
    }
}

# Opt-in is required even when running manually. No default execution or hidden probes.
if (-not $LiveReadOnly) {
    throw 'Refusing to invoke live diagnostics without explicit -LiveReadOnly.'
}

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..') -ErrorAction Stop).Path
$Branch = & git -C $Root branch --show-current
if ($LASTEXITCODE -ne 0 -or $Branch -ne 'feature/v0.7.0-monitoring' -or
    (Split-Path -Leaf $Root) -ne 'onyx-core-v070') {
    throw 'Runner is restricted to the v0.7.0 development worktree.'
}
& git -C $Root merge-base --is-ancestor '792526af8b8f3b66b7f8d05f4f289bf297f82593' HEAD
if ($LASTEXITCODE -ne 0) {
    throw 'Runner requires the verified Milestone 1 Checkpoint B lineage.'
}

$Collector = Join-Path $Root 'windows\networking\Collect-OnyxRecoveryEvidence.ps1'
if (-not (Test-Path -LiteralPath $Collector -PathType Leaf)) {
    throw 'Required read-only evidence collector is missing.'
}
$ExpectedHistory = Join-Path $env:LOCALAPPDATA `
    'OnyxCore-v070-Development\Monitoring\recovery-observations.json'

$Started = [DateTimeOffset]::UtcNow
# The collector enforces configuration validation, restricted SSH, history bounds
# and its own no-repair decisions. Do not duplicate probe implementations.
$Report = & $Collector -LiveReadOnly
$Finished = [DateTimeOffset]::UtcNow
$Summary = ConvertTo-OnyxCycleSummary -Report $Report `
    -StartedAt $Started -FinishedAt $Finished -ExpectedHistoryPath $ExpectedHistory

if ($Json) {
    $Summary | ConvertTo-Json -Depth 5 -Compress
}
else {
    $Summary
}
