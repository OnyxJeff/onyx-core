# Review-only by default. Stops/removes only the two v0.8 *development* logon tasks.
# No Git, production v0.7, protected installation, journal, or secret deletion.
[CmdletBinding()]
param([switch]$Remove, [switch]$ApproveTaskRemoval)
$ErrorActionPreference = 'Stop'
$Repo = 'D:\github_repos\onyx-core-v080'
$Names = @('ONYX CORE v0.8 - USB Monitor (User Session)',
           'ONYX CORE v0.8 - Incident Alerts (User Session)')
$Monitor = Join-Path $Repo 'windows\monitoring\v080\OnyxLiveIncidentHistory.py'
$Watcher = Join-Path $Repo 'windows\monitoring\v080\operations\Start-OnyxV080Alerts.ps1'
$Tasks = @(foreach ($Name in $Names) {
    Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
})
foreach ($Task in $Tasks) {
    if ($Task.Actions.Count -ne 1) { throw 'Unexpected task action count. STOP.' }
    $ExpectedPath = if ($Task.TaskName -eq $Names[0]) { $Monitor } else { $Watcher }
    if (-not $Task.Actions[0].Arguments.Contains($ExpectedPath)) {
        throw "Unexpected task action in $($Task.TaskName). STOP."
    }
    Write-Host "Detected: $($Task.TaskName) ($($Task.State))"
}
if (-not $Remove) {
    Write-Host 'PREVIEW ONLY: No tasks stopped or removed.'
    return
}
if (-not $ApproveTaskRemoval) { throw 'Task removal requires -ApproveTaskRemoval.' }
foreach ($Task in $Tasks) {
    if ($Task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $Task.TaskName -ErrorAction Stop
    }
    Unregister-ScheduledTask -TaskName $Task.TaskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed: $($Task.TaskName)"
}
Write-Host 'v0.8 logon tasks removed. Journals/DPAPI destination retained for review.'
Write-Host 'Verify no manually started/orphaned development processes remain before changing source.'
