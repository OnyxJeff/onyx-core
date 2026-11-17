# ONYX CORE v0.8.0 — OFFLINE/NO NETWORK route-evidence regression.
# Uses a temporary stand-in diagnostic and an isolated synthetic route function.
# Rewrites the route command ONLY in the temporary test copy; never calls live Find-NetRoute.
# Does not access the USB adapter, Pi, installed release or monitoring journals.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$Wrapper = Join-Path $Repo 'windows\monitoring\v080\Invoke-OnyxV080WindowsReadiness.ps1'
if (-not (Test-Path -LiteralPath $Wrapper -PathType Leaf)) {
    throw 'Expected development wrapper missing.'
}
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ('onyx-v080-route-offline-' + [guid]::NewGuid().ToString('N'))
$TempScript = Join-Path $TempRoot 'windows\monitoring\v080\Invoke-OnyxV080WindowsReadiness.ps1'
$TempDiagnostic = Join-Path $TempRoot 'windows\networking\Test-OnyxUsbIcsReadiness.ps1'
$Passed = 0

# The stub accepts the real diagnostic's parameters, returns synthetic values,
# and NEVER invokes Get-NetAdapter/Get-NetRoute/SSH or any network operation.
$Stub = @'
[CmdletBinding()]
param(
    [string]$AdapterName,
    [string]$GatewayIP,
    [string]$ReceiverIP,
    [int]$ReceiverPort,
    [int]$TimeoutMs
)
[PSCustomObject]@{
    Classification       = [string]$env:ONYX_V080_ROUTE_TEST_CLASS
    AdapterPresent        = $true
    AdapterUp             = $true
    GatewayPreferred      = $true
    RouteViaUsb           = ($env:ONYX_V080_ROUTE_TEST_CLASS -eq 'WindowsPathReady')
    SharedAccessStatus    = 'Running'
    ReceiverTcpReachable  = ($env:ONYX_V080_ROUTE_TEST_CLASS -eq 'WindowsPathReady')
    RepairAction          = 'None'
}
'@

# A unique synthetic function is called only from the disposable wrapper copy.
function global:Invoke-OnyxV080SyntheticRoute {
    [CmdletBinding()]
    param([string]$RemoteIPAddress)
    $env:ONYX_V080_ROUTE_TEST_CALLS = ([int]$env:ONYX_V080_ROUTE_TEST_CALLS + 1).ToString()
    if ($RemoteIPAddress -cne '192.168.137.167') {
        throw 'Synthetic test called Find-NetRoute for unexpected target.'
    }
    switch ($env:ONYX_V080_ROUTE_TEST_MODE) {
        'AccessDenied' { throw 'SYNTHETIC ACCESS DENIED' }
        'Empty' { return }
        'SourceOnly' {
            [PSCustomObject]@{ IPAddress='192.168.137.1'; InterfaceIndex=7 }
            return
        }
        'DisconnectedPair' {
            [PSCustomObject]@{ IPAddress='10.100.0.22'; InterfaceIndex=9 }
            [PSCustomObject]@{ DestinationPrefix='192.168.137.0/24'; NextHop='0.0.0.0'; InterfaceIndex=10 }
            return
        }
        'SelectedUsb' {
            [PSCustomObject]@{ IPAddress='192.168.137.1'; InterfaceIndex=7 }
            [PSCustomObject]@{ DestinationPrefix='192.168.137.0/24'; NextHop='0.0.0.0'; InterfaceIndex=7 }
            return
        }
        'ConfirmedOtherInterface' {
            [PSCustomObject]@{ IPAddress='10.100.0.22'; InterfaceIndex=9 }
            [PSCustomObject]@{ DestinationPrefix='192.168.137.167/32'; NextHop='10.100.0.1'; InterfaceIndex=9 }
            return
        }
        'ConfirmedWrongHop' {
            [PSCustomObject]@{ IPAddress='192.168.137.1'; InterfaceIndex=7 }
            [PSCustomObject]@{ DestinationPrefix='192.168.137.167/32'; NextHop='192.168.137.254'; InterfaceIndex=7 }
            return
        }
        'DuplicateSelections' {
            [PSCustomObject]@{ IPAddress='192.168.137.1'; InterfaceIndex=7 }
            [PSCustomObject]@{ IPAddress='10.100.0.22'; InterfaceIndex=9 }
            [PSCustomObject]@{ DestinationPrefix='192.168.137.0/24'; NextHop='0.0.0.0'; InterfaceIndex=7 }
            return
        }
        default { throw 'Unexpected synthetic route mode.' }
    }
}

function Assert-WrapperCase {
    param([string]$Name, [string]$DiagnosticClass, [string]$RouteMode,
          [bool]$ExpectedSuccess, [string]$ExpectedClass='')
    $env:ONYX_V080_ROUTE_TEST_MODE = $RouteMode
    $env:ONYX_V080_ROUTE_TEST_CLASS = $DiagnosticClass
    $env:ONYX_V080_ROUTE_TEST_CALLS = '0'
    $Caught = $false
    $Output = @()
    try {
        $Output = @(& $TempScript -LiveReadOnly -Json `
            -AdapterName 'Ethernet 3' -GatewayIP '192.168.137.1' `
            -ReceiverIP '192.168.137.167' -ReceiverPort 8765 -TimeoutMs 2000)
    }
    catch {
        $Caught = $true
        if ($_.Exception.Message -notlike '*route evidence*') {
            throw ('Unexpected error for ' + $Name + ': ' + $_.Exception.GetType().Name)
        }
    }
    if ($ExpectedSuccess -eq $Caught) {
        $Observed = if ($Caught) { 'REFUSED' } else { 'RETURNED' }
        $Expected = if ($ExpectedSuccess) { 'RETURNED' } else { 'REFUSED' }
        throw ('FAIL ' + $Name + ': expected ' + $Expected + '; observed ' + $Observed)
    }
    $ExpectedCalls = if ($DiagnosticClass -eq 'WindowsPathReady') { 0 } else { 1 }
    if ([int]$env:ONYX_V080_ROUTE_TEST_CALLS -ne $ExpectedCalls) {
        throw ('FAIL ' + $Name + ': synthetic route mock was not called exactly as expected')
    }
    if ($ExpectedSuccess) {
        if ($Output.Count -ne 1) { throw ('FAIL ' + $Name + ': invalid report count') }
        $Report = $Output[0] | ConvertFrom-Json
        if ($Report.classification -cne $ExpectedClass -or
            $Report.repair_action -cne 'None') {
            throw ('FAIL ' + $Name + ': wrong sanitized result')
        }
    }
    $script:Passed += 1
    Write-Host ('PASS: ' + $Name)
}

try {
    $Folder1 = Split-Path -Parent $TempScript
    $Folder2 = Split-Path -Parent $TempDiagnostic
    New-Item -Path $Folder1,$Folder2 -ItemType Directory -Force | Out-Null
    # Replace ONLY the queried command in the disposable wrapper copy.
    # This prevents calling real Find-NetRoute even if the mock is unavailable.
    $OriginalWrapper = [IO.File]::ReadAllText($Wrapper)
    $LiveCall = 'Find-NetRoute -RemoteIPAddress $ReceiverIP -ErrorAction Stop'
    $FakeCall = 'Invoke-OnyxV080SyntheticRoute -RemoteIPAddress $ReceiverIP -ErrorAction Stop'
    if ($OriginalWrapper.Split([string[]]@($LiveCall), [StringSplitOptions]::None).Count -ne 2) {
        throw 'Synthetic test wrapper route-call count mismatch. STOP.'
    }
    $SyntheticWrapper = $OriginalWrapper.Replace($LiveCall, $FakeCall)
    [IO.File]::WriteAllText($TempScript, $SyntheticWrapper, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText($TempDiagnostic, $Stub, [Text.UTF8Encoding]::new($false))

    # These are all synthetic. No real adapter/route command is used.
    Assert-WrapperCase 'legacy Healthy unchanged' 'WindowsPathReady' 'AccessDenied' $true 'WindowsPathReady'
    Assert-WrapperCase 'real alternative route remains degraded' 'RouteNotViaUsb' 'ConfirmedOtherInterface' $true 'RouteNotViaUsb'
    Assert-WrapperCase 'real non-direct next hop remains degraded' 'RouteNotViaUsb' 'ConfirmedWrongHop' $true 'RouteNotViaUsb'
    Assert-WrapperCase 'route access denied refuses false degraded' 'RouteNotViaUsb' 'AccessDenied' $false
    Assert-WrapperCase 'empty route evidence refuses false degraded' 'RouteNotViaUsb' 'Empty' $false
    Assert-WrapperCase 'missing route object refuses false degraded' 'RouteNotViaUsb' 'SourceOnly' $false
    Assert-WrapperCase 'disconnected source and route refuse false degraded' 'RouteNotViaUsb' 'DisconnectedPair' $false
    Assert-WrapperCase 'conflicting legacy vs independently valid route refuses' 'RouteNotViaUsb' 'SelectedUsb' $false
    Assert-WrapperCase 'ambiguous duplicate selection refuses' 'RouteNotViaUsb' 'DuplicateSelections' $false
    Write-Host ("PASS: $Passed offline cases; no live diagnostics or host mutations.")
}
finally {
    Remove-Item Env:ONYX_V080_ROUTE_TEST_CLASS -ErrorAction SilentlyContinue
    Remove-Item Env:ONYX_V080_ROUTE_TEST_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:ONYX_V080_ROUTE_TEST_CALLS -ErrorAction SilentlyContinue
    Remove-Item Function:\Invoke-OnyxV080SyntheticRoute -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
