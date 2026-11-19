# ONYX CORE v0.9.0 upgrade: READ-ONLY Windows operator preflight.
# No task XML is exported and no executable/arguments are printed.
# Does not open DPAPI files, write files, contact Pi or install/activate code.
[CmdletBinding()]
param(
    [ValidatePattern('^[a-f0-9]{40}$')]
    [string]$ExpectedProductionCommit = '06ec81582791fc797f74ad294195d68b2023cb66',
    [ValidatePattern('^[a-f0-9]{40}$')]
    [string]$ExpectedDevelopmentCommit = '8a8007d925fedc4eb31a3e1bc9a68109b3373312'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
$Production = 'D:\github_repos\onyx-core'
$Development = 'D:\github_repos\onyx-core-v090'
$ProductionHead = (& git -C $Production rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $ProductionHead -cne $ExpectedProductionCommit) {
    throw 'Production source commit differs from pinned baseline. STOP.'
}
$DevelopmentHead = (& git -C $Development rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $DevelopmentHead -cne $ExpectedDevelopmentCommit) {
    throw 'Development commit differs from expected checkpoint. STOP.'
}
$Dirty = @(& git -C $Development status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw 'Development Git status failed.' }
$RequiredNames = @('ONYX CORE - Telemetry Collector', 'ONYX CORE - Local Gateway')
$TaskRows = @()
foreach ($Name in $RequiredNames) {
    $Task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    if ($null -eq $Task -or @($Task.Actions).Count -ne 1) {
        throw 'A production task is missing or does not have exactly one action.'
    }
    $Action = $Task.Actions[0]
    $ArgumentString = [string]$Action.Execute + ' ' + [string]$Action.Arguments + ' ' + [string]$Action.WorkingDirectory
    $ReferencesProduction = $ArgumentString.IndexOf($Production, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if (-not $ReferencesProduction) { throw 'Production task no longer points to the audited repository. STOP.' }
    $TaskRows += [ordered]@{
        name = $Name
        state = [string]$Task.State
        references_expected_production = $ReferencesProduction
        action_count = @($Task.Actions).Count
        logon_type = [string]$Task.Principal.LogonType
        run_level = [string]$Task.Principal.RunLevel
    }
}
$CandidateNames = @('ONYX CORE v0.9 - Telemetry Collector (Candidate)', 'ONYX CORE v0.9 - Local Gateway (Candidate)')
$CandidateExisting = @($CandidateNames | Where-Object { $null -ne (Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue) })
$Result = [ordered]@{
    schema_version = 1
    operation = 'READ_ONLY_UPGRADE_PREFLIGHT'
    production_commit = $ProductionHead
    development_commit = $DevelopmentHead
    development_changes = $Dirty.Count
    original_tasks = $TaskRows
    candidate_tasks_present = $CandidateExisting.Count
    protected_v080_present = (Test-Path -LiteralPath 'C:\Program Files\OnyxCore\v0.8.0' -PathType Container)
    protected_v080_anchor_present = (Test-Path -LiteralPath 'C:\Program Files\OnyxCore\v0.8.0-release.sha256' -PathType Leaf)
    candidate_v090_installed = (Test-Path -LiteralPath 'C:\Program Files\OnyxCore\v0.9.0' -PathType Container)
    credential_content_read = $false
    task_definitions_changed = $false
    authorized_cutover = $false
}
$Result | ConvertTo-Json -Depth 6
