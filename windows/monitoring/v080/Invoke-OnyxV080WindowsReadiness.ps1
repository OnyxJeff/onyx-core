# ONYX CORE v0.8.0 M1 — read-only Windows side of a single connectivity check.
# No Task Scheduler registration, recovery, repair, state writes or elevation.
# Invoked only by OnyxLiveConnectivity.py with explicit -LiveReadOnly.
[CmdletBinding()]
param(
    [switch]$LiveReadOnly,
    [switch]$Json,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$')]
    [string]$AdapterName,
    [ValidatePattern('^\d{1,3}(\.\d{1,3}){3}$')]
    [string]$GatewayIP,
    [ValidatePattern('^\d{1,3}(\.\d{1,3}){3}$')]
    [string]$ReceiverIP,
    [ValidateRange(1,65535)][int]$ReceiverPort,
    [ValidateRange(100,10000)][int]$TimeoutMs
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $LiveReadOnly) {
    throw 'Explicit -LiveReadOnly required; no probe was run.'
}
if ($PSVersionTable.PSVersion.Major -ne 5 -or
    $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}

$Diagnostic = Join-Path $PSScriptRoot '..\..\networking\Test-OnyxUsbIcsReadiness.ps1'
if (-not (Test-Path -LiteralPath $Diagnostic -PathType Leaf)) {
    throw 'Existing read-only Windows diagnostic missing.'
}
$Result = & $Diagnostic -AdapterName $AdapterName `
    -GatewayIP $GatewayIP -ReceiverIP $ReceiverIP `
    -ReceiverPort $ReceiverPort -TimeoutMs $TimeoutMs
if ($null -eq $Result -or $Result -is [array] -or
    $Result.RepairAction -ne 'None' -or
    [string]::IsNullOrWhiteSpace([string]$Result.Classification)) {
    throw 'Read-only Windows diagnostic returned an invalid result.'
}

$Summary = [ordered]@{
    schema_version           = 1
    source                   = 'OnyxV080WindowsUsbReadiness'
    classification           = [string]$Result.Classification
    adapter_present          = [bool]$Result.AdapterPresent
    adapter_up               = [bool]$Result.AdapterUp
    gateway_preferred        = [bool]$Result.GatewayPreferred
    route_via_usb            = [bool]$Result.RouteViaUsb
    ics_service_status       = [string]$Result.SharedAccessStatus
    receiver_tcp_reachable   = [bool]$Result.ReceiverTcpReachable
    repair_action            = 'None'
}
if ($Json) {
    $Summary | ConvertTo-Json -Depth 4 -Compress
}
else {
    [PSCustomObject]$Summary
}
