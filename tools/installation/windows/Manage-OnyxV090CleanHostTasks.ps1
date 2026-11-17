# ONYX CORE v0.9.0 clean-host task registration. Windows PowerShell 5.1.
# PREVIEW by default. On SQUALL or another existing ONYX host registration refuses.
# No production task replacement, no credential creation, no installation or task start.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
    [switch]$Register,
    [switch]$ApproveNewLogonTasks,
    [switch]$Unregister,
    [switch]$ApproveTaskRemoval
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
if ($Register -and $Unregister) { throw 'Register and Unregister are mutually exclusive.' }
if ($ApproveNewLogonTasks -and -not $Register) { throw 'Registration approval without -Register refused.' }
if ($ApproveTaskRemoval -and -not $Unregister) { throw 'Removal approval without -Unregister refused.' }
if ($Register -and -not $ApproveNewLogonTasks) { throw 'Explicit registration approval missing.' }
if ($Unregister -and -not $ApproveTaskRemoval) { throw 'Explicit removal approval missing.' }

$Root = 'C:\Program Files\OnyxCore\v0.9.0'
$Python = 'C:\Python313\python.exe'
$Pythonw = 'C:\Python313\pythonw.exe'
$Planner = Join-Path $Root 'tools\installation\common\onyx_runtime_plan.py'
$Vbs = Join-Path $Root 'windows\collector\Launch-OnyxTelemetry.vbs'
$Gateway = Join-Path $Root 'windows\gateway\OnyxGateway.py'
$Dashboard = Join-Path $Root 'windows\gateway\gateway-dashboard.html'
$TokenFile = Join-Path $env:LOCALAPPDATA 'OnyxCore\collector-token.dpapi'
$NameCollector = 'ONYX CORE v0.9 - Telemetry Collector (Candidate)'
$NameGateway = 'ONYX CORE v0.9 - Local Gateway (Candidate)'
$ProductionNames = @('ONYX CORE - Telemetry Collector', 'ONYX CORE - Local Gateway')
$TaskNames = @($NameCollector, $NameGateway)
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$VbsExe = Join-Path $env:WINDIR 'System32\wscript.exe'
$CollectorArgs = ('"{0}"' -f $Vbs)
$GatewayArgs = ('-I -B "{0}" --dashboard "{1}" --receiver svr-onyxcore.local --port 18769 --load-dpapi' -f $Gateway, $Dashboard)

foreach ($File in @($Python, $Pythonw, $Planner, $Vbs, $Gateway, $Dashboard, $VbsExe)) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
        throw ('Required clean-install component missing: ' + $File)
    }
}
# On v0.8 this runs a complete package-file hash audit and refuses modified source.
$AuditLines = @(& $Python -I -B $Planner --installed-root $Root --platform windows --expected-commit $ExpectedCommit 2>&1)
if ($LASTEXITCODE -ne 0 -or $AuditLines.Count -ne 1) {
    throw 'Installed package provenance audit refused; no task changes.'
}
$Audit = $AuditLines[0] | ConvertFrom-Json
if ($Audit.operation -ne 'READ_ONLY_ACTIVATION_PLAN' -or
    $Audit.activated -ne $false -or
    $Audit.audit.platform -ne 'windows' -or
    $Audit.audit.source_commit -cne $ExpectedCommit -or
    $Audit.proposal.candidate_gateway_loopback_port -ne 18769) {
    throw 'Unexpected runtime plan. No task changes.'
}

$Admin = New-Object -TypeName Security.Principal.WindowsPrincipal -ArgumentList ([Security.Principal.WindowsIdentity]::GetCurrent())
if ($Admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run as the normal intended Windows user, not an elevated administrator.'
}
if (-not [Environment]::UserInteractive) { throw 'Interactive user session required.' }

$Registered = @()
foreach ($Name in $TaskNames) {
    $Task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($null -ne $Task) { $Registered += $Task }
}
Write-Host '=== ONYX CORE v0.9 CLEAN-HOST TASK PLAN ==='
Write-Host "Validated commit: $ExpectedCommit"
Write-Host "Identity: $Identity; tasks found: $($Registered.Count)"
Write-Host 'Candidate port 18769; existing v0.7/v0.8 ports unchanged.'
Write-Host 'No credential reads, task starts, repairs, or production replacement.'
if (-not $Register -and -not $Unregister) {
    Write-Host ('DPAPI token exists: ' + (Test-Path -LiteralPath $TokenFile -PathType Leaf))
    Write-Host 'PREVIEW ONLY: no tasks changed.'
    return
}
if ($Register) {
    if ($Registered.Count -ne 0) { throw 'Candidate task already registered; no overwrite.' }
    foreach ($Name in $ProductionNames) {
        if ($null -ne (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue)) {
            throw 'Existing production ONYX tasks detected. Clean-host registration refused.'
        }
    }
    if (-not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) {
        throw 'User-scoped DPAPI token missing; enroll explicitly before registration.'
    }
    $Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity
    $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([timespan]::Zero) -AllowStartIfOnBatteries
    $One = New-ScheduledTaskAction -Execute $VbsExe -Argument $CollectorArgs -WorkingDirectory (Split-Path -Parent $Vbs)
    $Two = New-ScheduledTaskAction -Execute $Pythonw -Argument $GatewayArgs -WorkingDirectory (Split-Path -Parent $Gateway)
    $Created = @()
    try {
        Register-ScheduledTask -TaskName $NameCollector -Action $One -Trigger $Trigger `
            -Principal $Principal -Settings $Settings -ErrorAction Stop | Out-Null
        $Created += $NameCollector
        Register-ScheduledTask -TaskName $NameGateway -Action $Two -Trigger $Trigger `
            -Principal $Principal -Settings $Settings -ErrorAction Stop | Out-Null
        $Created += $NameGateway
    } catch {
        foreach ($Name in $Created) {
            Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
        }
        throw 'Candidate registration failed; newly-created task(s) rolled back.'
    }
    Write-Host 'Registered two opt-in user-logon candidate tasks; NOT started. No existing tasks changed.'
    Write-Host 'WARNING: These tasks can run automatically at the NEXT user logon. Use only on a clean host.'
    return
}
if ($Registered.Count -ne 2) { throw 'Both exact candidate tasks must exist to unregister.' }
foreach ($Task in $Registered) {
    $ExpectedExe = if ($Task.TaskName -eq $NameCollector) { $VbsExe } else { $Pythonw }
    $ExpectedArgs = if ($Task.TaskName -eq $NameCollector) { $CollectorArgs } else { $GatewayArgs }
    if ($Task.State -eq 'Running') { throw 'Candidate task running; manual approved stop required.' }
    if ($Task.Actions.Count -ne 1 -or
        $Task.Actions[0].Execute -ine $ExpectedExe -or
        $Task.Actions[0].Arguments -cne $ExpectedArgs -or
        $Task.Principal.UserId -ine $Identity -or
        $Task.Principal.LogonType -ne 'Interactive' -or
        $Task.Principal.RunLevel -ne 'Limited') {
        throw 'Candidate task was modified; refusing removal.'
    }
}
foreach ($Name in $TaskNames) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction Stop
}
Write-Host 'Removed only the two verified, stopped v0.9 candidate tasks. Source and state retained.'
