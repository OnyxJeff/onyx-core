# ONYX CORE v1.0.0 M1-S2 offline-only unit tests.
# Windows PowerShell 5.1. Does not run the host readiness probe.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$Core = Join-Path $Repo 'tools\installation\windows\OnyxV100ReadinessCore.ps1'
$Main = Join-Path $Repo 'tools\installation\windows\Invoke-OnyxV100Readiness.ps1'

foreach ($file in @($Core, $Main, $PSCommandPath)) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $file, [ref]$tokens, [ref]$errors)
    if ($null -ne $errors -and @($errors).Count -gt 0) {
        throw ('FAIL: PowerShell 5.1 parser error in ' + $file)
    }
}
Write-Host 'PASS: All M1-S2 PowerShell files parse.'

. $Core

$good = Test-OnyxV100PythonVersion -VersionText 'Python 3.13.8'
$bad = Test-OnyxV100PythonVersion -VersionText 'Python 3.12.9'
$empty = Test-OnyxV100PythonVersion -VersionText 'not a python interpreter'
if (-not $good.supported -or $good.version -cne '3.13.8' -or
    $bad.supported -or $empty.supported) {
    throw 'FAIL: Python version policy incorrect.'
}
Write-Host 'PASS: Python 3.13-only policy and malformed output.'

if (-not (Test-OnyxV100UsbHint -Name 'Ethernet 3' -Description 'Raspberry Pi USB Remote NDIS Network Device')) {
    throw 'FAIL: RNDIS hint not recognized.'
}
if (Test-OnyxV100UsbHint -Name 'Ethernet' -Description 'Intel(R) Ethernet Connection') {
    throw 'FAIL: Ordinary LAN incorrectly treated as USB gadget.'
}
Write-Host 'PASS: USB interface hint classification.'

$blocked = Get-OnyxV100ReadinessDecision -Windows11 $false -PowerShell51 $true `
    -PythonSupported $false -TaskSchedulerAvailable $true -UsbCandidates 0 `
    -DpapiTokenPresent $false -ExistingOnyxTasks $false
if ($blocked.state -cne 'BLOCKED' -or $blocked.blockers.Count -ne 2 -or
    $blocked.installation_accepted) {
    throw 'FAIL: Blocker logic or acceptance boundary incorrect.'
}

$existing = Get-OnyxV100ReadinessDecision -Windows11 $true -PowerShell51 $true `
    -PythonSupported $true -TaskSchedulerAvailable $true -UsbCandidates 1 `
    -DpapiTokenPresent $true -ExistingOnyxTasks $true
if ($existing.state -cne 'REQUIRES_CONFIGURATION' -or
    -not $existing.supported_base_prerequisites -or
    $existing.installation_accepted -or
    @($existing.operator_actions | Where-Object { $_ -like '*upgrade workflow*' }).Count -ne 1) {
    throw 'FAIL: Existing-installation separation incorrect.'
}
Write-Host 'PASS: Blocked and upgrade-host decisions.'

$source = [IO.File]::ReadAllText($Main)
foreach ($forbidden in @('Register-ScheduledTask', 'Start-ScheduledTask',
    'Stop-ScheduledTask', 'Set-NetIPInterface', 'Set-NetIPAddress',
    'Enable-NetAdapter', 'Set-Content', 'New-Item', 'Invoke-RestMethod')) {
    if ($source.IndexOf($forbidden, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw ('FAIL: Forbidden command found: ' + $forbidden)
    }
}
Write-Host 'PASS: Basic no-mutation command inventory.'
Write-Host 'SUCCESS: M1-S2 offline PowerShell checks passed.'
