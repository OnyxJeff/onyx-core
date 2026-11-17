# Protected release task installer. Inert unless -Install and explicit approval.
# This script must be installed under the admin-owned source and pinned in the
# release manifest. No Git checkout, repairs, credential changes, or task start.
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$ApproveUserLogonTasks,
    [switch]$EnableDiscordAlerts
)
$ErrorActionPreference = 'Stop'
$Root = 'C:\Program Files\OnyxCore\v0.8.0'
$Python = 'C:\Python313\python.exe'
$Powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Ops = Join-Path $Root 'windows\monitoring\v080\operations'
$Self = Join-Path $Ops 'Install-OnyxV080ProtectedUserTasks.ps1'
$Monitor = Join-Path $Root 'windows\monitoring\v080\OnyxV080ProtectedLogonRuntime.py'
$Operator = Join-Path $Root 'windows\monitoring\v080\OnyxV080ReleaseOperator.py'
$Alerts = Join-Path $Ops 'Start-OnyxV080ProtectedDiscord.ps1'
$MonitorName = 'ONYX CORE v0.8 - USB Monitor (Protected)'
$AlertName = 'ONYX CORE v0.8 - Discord Alerts (Protected)'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$CredentialFolder = Join-Path $env:LOCALAPPDATA 'OnyxCore-v080-Development\NotificationConfig'
$ConfigFiles = @((Join-Path $CredentialFolder 'destination.dpapi'),
                 (Join-Path $CredentialFolder 'provider.txt'))

if (-not [string]::Equals($MyInvocation.MyCommand.Path, $Self,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Protected installer must execute from fixed administrator-owned location.'
}
foreach ($Item in @($Python,$Powershell,$Monitor,$Operator,$Alerts)) {
    if (-not (Test-Path -LiteralPath $Item -PathType Leaf)) {
        throw 'Protected source/runner prerequisite missing.'
    }
}
$InstalledAudit = @(& $Python -I -B $Operator --audit-installed)
if ($LASTEXITCODE -ne 0 -or $InstalledAudit.Count -ne 1) {
    throw 'Protected source and approval audit failed. No tasks changed.'
}
$Audit = $InstalledAudit[0] | ConvertFrom-Json
if ($Audit.result -ne 'PASS' -or $Audit.mode -ne 'audit-only' -or
    $Audit.operator_session -ne 'active-local-console' -or
    $Audit.verified_sources -ne 24) {
    throw 'Expected 24-file protected approval not installed. No tasks changed.'
}
$IdentityPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if ($IdentityPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Use normal non-elevated user session for task installation.'
}
$Existing = @(
    Get-ScheduledTask -TaskName $MonitorName,$AlertName,
        'ONYX CORE v0.8 - USB Monitor (User Session)',
        'ONYX CORE v0.8 - Incident Alerts (User Session)' -ErrorAction SilentlyContinue
)
if ($Existing.Count -gt 0) { throw 'Existing development/protected v0.8 task found. STOP.' }
if ($EnableDiscordAlerts) {
    foreach ($Item in $ConfigFiles) {
        if (-not (Test-Path -LiteralPath $Item -PathType Leaf)) {
            throw 'Discord DPAPI configuration missing.'
        }
    }
    if (([IO.File]::ReadAllText($ConfigFiles[1], [Text.Encoding]::ASCII)).Trim() -ne 'discord') {
        throw 'Only the approved private Discord destination is supported.'
    }
}
Write-Host '=== ONYX CORE v0.8 PROTECTED USER-LOGON TASK PREVIEW ==='
Write-Host "Approved source: $($Audit.source_commit)"
Write-Host "Identity: $Identity"
Write-Host "Monitor: $MonitorName (20-cycle bounded sessions, 120s interval)"
Write-Host "Discord: $(if ($EnableDiscordAlerts) {$AlertName} else {'not requested'})"
Write-Host 'No auto-enrollment, no grant renewal, no task start, no network repair.'
Write-Host 'After existing grant expiry, monitoring stops until manually reapproved.'
if (-not $Install) {
    Write-Host 'PREVIEW ONLY: No Scheduled Tasks changed.'
    return
}
if (-not $ApproveUserLogonTasks) { throw 'Explicit -ApproveUserLogonTasks required.' }
$Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$MonitorAction = New-ScheduledTaskAction -Execute $Python `
    -Argument ('-I -B "{0}" --run-approved-monitor' -f $Monitor) `
    -WorkingDirectory $Root
$MonitorDef = New-ScheduledTask -Action $MonitorAction -Trigger $Trigger `
    -Settings $Settings -Principal $Principal
$Registered = @()
try {
    Register-ScheduledTask -TaskName $MonitorName -InputObject $MonitorDef -ErrorAction Stop | Out-Null
    $Registered += $MonitorName
    if ($EnableDiscordAlerts) {
        $AlertAction = New-ScheduledTaskAction -Execute $Powershell `
            -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ApproveProtectedAlerts' -f $Alerts) `
            -WorkingDirectory $Root
        $AlertDef = New-ScheduledTask -Action $AlertAction -Trigger $Trigger `
            -Settings $Settings -Principal $Principal
        Register-ScheduledTask -TaskName $AlertName -InputObject $AlertDef -ErrorAction Stop | Out-Null
        $Registered += $AlertName
    }
}
catch {
    foreach ($Name in $Registered) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    }
    throw 'Protected task installation failed; newly registered tasks rolled back.'
}
Write-Host 'PASS: Protected user-logon task(s) registered but NOT STARTED.'
