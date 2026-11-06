# ONYX CORE v0.6.0 — Read-only Windows USB/ICS diagnostics
# No service changes, network configuration changes, or repair actions.

[CmdletBinding()]
param(
    [string]$AdapterName = 'Ethernet 3',
    [string]$GatewayIP = '192.168.137.1',
    [string]$ReceiverIP = '192.168.137.167',
    [ValidateRange(1,65535)]
    [int]$ReceiverPort = 8765,
    [ValidateRange(100,10000)]
    [int]$TimeoutMs = 2000,
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-OnyxClassification {
    param(
        [bool]$AdapterPresent,
        [bool]$AdapterUp,
        [bool]$GatewayPreferred,
        [bool]$RouteViaUsb,
        [bool]$IcsRunning,
        [bool]$ReceiverReachable
    )

    if (-not $AdapterPresent) {
        return 'AdapterMissing'
    }
    if (-not $AdapterUp) {
        return 'AdapterDown'
    }
    if (-not $GatewayPreferred) {
        return 'GatewayAddressMissing'
    }
    if (-not $RouteViaUsb) {
        return 'RouteNotViaUsb'
    }
    if (-not $IcsRunning) {
        return 'IcsServiceStopped'
    }
    if (-not $ReceiverReachable) {
        return 'ReceiverUnreachable'
    }

    return 'WindowsPathReady'
}

function Test-OnyxTcpPort {
    param(
        [string]$Address,
        [int]$Port,
        [int]$Timeout
    )

    $Client = New-Object System.Net.Sockets.TcpClient
    $Async = $null

    try {
        $Async = $Client.BeginConnect(
            $Address, $Port, $null, $null
        )

        if (-not $Async.AsyncWaitHandle.WaitOne($Timeout)) {
            return $false
        }

        $Client.EndConnect($Async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $Async) {
            $Async.AsyncWaitHandle.Close()
        }
        $Client.Close()
    }
}

if ($SelfTest) {
    $Cases = @(
        @('AdapterMissing', $false, $false, $false, $false, $false),
        @('AdapterDown', $true, $false, $false, $true, $false),
        @('GatewayAddressMissing', $true, $true, $false, $true, $false),
        @('IcsServiceStopped', $true, $true, $true, $false, $true),
        @('ReceiverUnreachable', $true, $true, $true, $true, $false),
        @('WindowsPathReady', $true, $true, $true, $true, $true)
    )

    foreach ($Case in $Cases) {
        $Actual = Get-OnyxClassification `
            -AdapterPresent $Case[1] `
            -AdapterUp $Case[2] `
            -GatewayPreferred $Case[3] `
            -RouteViaUsb $true `
            -IcsRunning $Case[4] `
            -ReceiverReachable $Case[5]

        if ($Actual -ne $Case[0]) {
            throw "FAIL: Expected $($Case[0]), got $Actual"
        }

        Write-Host "PASS: $($Case[0])"
    }

    $RouteTest = Get-OnyxClassification `
        -AdapterPresent $true `
        -AdapterUp $true `
        -GatewayPreferred $true `
        -RouteViaUsb $false `
        -IcsRunning $true `
        -ReceiverReachable $true

    if ($RouteTest -ne 'RouteNotViaUsb') {
        throw 'FAIL: RouteNotViaUsb'
    }

    Write-Host 'PASS: RouteNotViaUsb'
    Write-Host 'PASS: All 7 classification tests.'
    return
}

# Gather read-only Windows state.
$Adapter = Get-NetAdapter -Name $AdapterName `
    -ErrorAction SilentlyContinue

$AdapterPresent = ($null -ne $Adapter)
$AdapterUp = (
    $AdapterPresent -and $Adapter.Status -eq 'Up'
)

$Addresses = @(
    Get-NetIPAddress `
        -InterfaceAlias $AdapterName `
        -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -eq $GatewayIP -and
        $_.AddressState -eq 'Preferred'
    }
)

$GatewayPreferred = ($Addresses.Count -gt 0)

$Service = Get-Service -Name SharedAccess `
    -ErrorAction SilentlyContinue

$IcsRunning = (
    $null -ne $Service -and
    $Service.Status -eq 'Running'
)

$ServiceStatus = if ($null -eq $Service) {
    'NotFound'
} else {
    [string]$Service.Status
}

# Verify Windows selects the intended direct USB route.
$RouteViaUsb = $false

if ($AdapterUp -and $GatewayPreferred) {
    try {
        $Selection = @(
            Find-NetRoute -RemoteIPAddress $ReceiverIP -ErrorAction Stop
        )

        $SourceMatch = @($Selection | Where-Object {
            $_.PSObject.Properties['IPAddress'] -and
            $_.IPAddress -eq $GatewayIP -and
            $_.InterfaceIndex -eq $Adapter.ifIndex
        })

        $RouteMatch = @($Selection | Where-Object {
            $_.PSObject.Properties['DestinationPrefix'] -and
            $_.DestinationPrefix -and
            $_.InterfaceIndex -eq $Adapter.ifIndex -and
            $_.NextHop -eq '0.0.0.0'
        })

        $RouteViaUsb = (
            $SourceMatch.Count -gt 0 -and
            $RouteMatch.Count -gt 0
        )
    }
    catch {
        $RouteViaUsb = $false
    }
}

# TCP test proves only Windows-to-Pi receiver reachability.
$ReceiverReachable = $false

if ($AdapterUp -and $GatewayPreferred -and $RouteViaUsb) {
    $ReceiverReachable = Test-OnyxTcpPort `
        -Address $ReceiverIP `
        -Port $ReceiverPort `
        -Timeout $TimeoutMs
}

$Classification = Get-OnyxClassification `
    -AdapterPresent $AdapterPresent `
    -AdapterUp $AdapterUp `
    -GatewayPreferred $GatewayPreferred `
    -RouteViaUsb $RouteViaUsb `
    -IcsRunning $IcsRunning `
    -ReceiverReachable $ReceiverReachable

[PSCustomObject]@{
    TimestampUTC          = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    Classification        = $Classification
    AdapterName           = $AdapterName
    AdapterPresent        = $AdapterPresent
    AdapterUp             = $AdapterUp
    GatewayIP             = $GatewayIP
    GatewayPreferred      = $GatewayPreferred
    RouteViaUsb           = $RouteViaUsb
    SharedAccessStatus    = $ServiceStatus
    ReceiverIP            = $ReceiverIP
    ReceiverPort          = $ReceiverPort
    ReceiverTcpReachable  = $ReceiverReachable
    PiInternetForwarding  = 'NotTested'
    RepairAction          = 'None'
}
