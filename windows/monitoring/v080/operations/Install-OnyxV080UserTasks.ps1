# Review-only by default; user-logon development task installer.
# This is NOT the protected Program Files runtime and does not change v0.7.0.
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$ApproveUserLogonTasks,
    [switch]$EnableAlerts
)
$ErrorActionPreference = 'Stop'
$Repo = 'D:\github_repos\onyx-core-v080'
$Branch = 'feature/v0.8.0-continuous-monitoring'
$Python = 'C:\Python313\python.exe'
$Powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$M3 = Join-Path $Repo 'windows\monitoring\v080\OnyxLiveIncidentHistory.py'
$StartAlerts = Join-Path $Repo 'windows\monitoring\v080\operations\Start-OnyxV080Alerts.ps1'
$Url = Join-Path $env:LOCALAPPDATA 'OnyxCore-v080-Development\NotificationConfig\destination.dpapi'
$Provider = Join-Path $env:LOCALAPPDATA 'OnyxCore-v080-Development\NotificationConfig\provider.txt'
$MonitorTask = 'ONYX CORE v0.8 - USB Monitor (User Session)'
$AlertTask = 'ONYX CORE v0.8 - Incident Alerts (User Session)'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

foreach ($Path in @($Python,$Powershell,$M3,$StartAlerts)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Missing required runtime/script for user-logon monitoring.'
    }
}
$Current = & git -C $Repo branch --show-current
if ($LASTEXITCODE -ne 0 -or $Current -ne $Branch) {
    throw 'This workflow is restricted to the v0.8.0 development branch.'
}
$Head = & git -C $Repo rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Unable to identify Git commit.' }
$Already = @(Get-ScheduledTask -TaskName $MonitorTask,$AlertTask -ErrorAction SilentlyContinue)
if ($Already.Count) { throw 'Onyx v0.8 logon task(s) already exist; no overwrite permitted.' }
if ($EnableAlerts -and ((-not (Test-Path -LiteralPath $Url)) -or
                        (-not (Test-Path -LiteralPath $Provider)))) {
    throw 'Alert destination must first be stored by Set-OnyxV080Notification.ps1.'
}
Write-Host '=== ONYX CORE v0.8 USER SESSION TASK REVIEW ==='
Write-Host "Git HEAD: $Head"
Write-Host "Logon identity: $Identity"
Write-Host 'Mode: User-logon; no elevation; no service; no repairs; no v0.7 changes.'
Write-Host "Monitor: $MonitorTask (120-second checks, 3/5-minute incident confirm, 2 healthy to recover)"
Write-Host "Watcher: $(if ($EnableAlerts) {$AlertTask} else {'not requested'})"
Write-Host 'Note: shutdown/sleep, no login, or host network loss may prevent local alerts.'
if (-not $Install) {
    Write-Host 'PREVIEW ONLY: no Scheduled Tasks changed.'
    return
}
if (-not $ApproveUserLogonTasks) { throw 'Installation requires -ApproveUserLogonTasks.' }
$Dirty = @(& git -C $Repo status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $Dirty.Count -ne 0) {
    throw 'Uncommitted source/scripts are not permitted for task installation.'
}
# Prevent inherited run-as SYSTEM or administrator; task is current user,
# only when logged in. No password and no 'run whether logged in or not'.
$Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$MonitorAction = New-ScheduledTaskAction -Execute $Python `
    -Argument ('-B "{0}" --record-live --continuous --interval-seconds 120 --confirmed-incidents' -f $M3) `
    -WorkingDirectory $Repo
$MonitorDef = New-ScheduledTask -Action $MonitorAction -Trigger $Trigger `
    -Settings $Settings -Principal $Principal
Register-ScheduledTask -TaskName $MonitorTask -InputObject $MonitorDef -ErrorAction Stop | Out-Null
if ($EnableAlerts) {
    $AlertAction = New-ScheduledTaskAction -Execute $Powershell `
        -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $StartAlerts) `
        -WorkingDirectory $Repo
    $AlertDef = New-ScheduledTask -Action $AlertAction -Trigger $Trigger `
        -Settings $Settings -Principal $Principal
    Register-ScheduledTask -TaskName $AlertTask -InputObject $AlertDef -ErrorAction Stop | Out-Null
}
Write-Host 'User-logon tasks registered (not started by this installer).'
Write-Host 'Review task actions/settings and start only with explicit authorization.'
