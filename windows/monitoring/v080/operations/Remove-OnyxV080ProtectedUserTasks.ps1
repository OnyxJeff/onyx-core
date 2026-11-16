# Protected task rollback: review-only unless explicit -Remove and -ApproveTaskRemoval.
# Never deletes journals, credentials, source, production tasks or service state.
[CmdletBinding()]
param([switch]$Remove,[switch]$ApproveTaskRemoval)
$ErrorActionPreference = 'Stop'
$Root = 'C:\Program Files\OnyxCore\v0.8.0'
$Ops = Join-Path $Root 'windows\monitoring\v080\operations'
$Self = Join-Path $Ops 'Remove-OnyxV080ProtectedUserTasks.ps1'
$Monitor = Join-Path $Root 'windows\monitoring\v080\OnyxV080ProtectedLogonRuntime.py'
$Discord = Join-Path $Ops 'Start-OnyxV080ProtectedDiscord.ps1'
$Definitions = @(
    @{ Name = 'ONYX CORE v0.8 - USB Monitor (Protected)'; Expected = ('-I -B "{0}" --run-approved-monitor' -f $Monitor) },
    @{ Name = 'ONYX CORE v0.8 - Discord Alerts (Protected)'; Expected = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ApproveProtectedAlerts' -f $Discord) }
)
if (-not [string]::Equals($MyInvocation.MyCommand.Path, $Self,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Protected rollback must execute from fixed installation.'
}
$Found = @()
foreach ($Definition in $Definitions) {
    $Task = Get-ScheduledTask -TaskName $Definition.Name -ErrorAction SilentlyContinue
    if ($null -eq $Task) { continue }
    if ($Task.Actions.Count -ne 1 -or
        $Task.Actions[0].Arguments -cne $Definition.Expected) {
        throw "Unexpected registered task action for $($Definition.Name). STOP."
    }
    if ($Task.Principal.LogonType -ne 'Interactive' -or
        $Task.Principal.RunLevel -ne 'Limited') {
        throw "Unexpected task security principal for $($Definition.Name). STOP."
    }
    $Found += $Task
    Write-Host "Verified task: $($Task.TaskName), state $($Task.State)"
}
if (-not $Remove) {
    Write-Host 'PREVIEW ONLY: No tasks stopped or removed.'
    return
}
if (-not $ApproveTaskRemoval) { throw 'Explicit -ApproveTaskRemoval required.' }
foreach ($Task in $Found) {
    if ($Task.State -eq 'Running') { Stop-ScheduledTask -TaskName $Task.TaskName -ErrorAction Stop }
    Unregister-ScheduledTask -TaskName $Task.TaskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed: $($Task.TaskName)"
}
Write-Host 'Rollback complete: journals, DPAPI configuration, and v0.7.0 preserved.'
