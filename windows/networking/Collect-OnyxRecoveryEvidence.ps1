# ONYX CORE v0.6.0 - single-run, read-only evidence integration.
# No scheduled tasks, service restarts, network changes, or persistent state.
[CmdletBinding()]
param(
    [string]$PiHostName = 'svr-onyxcore.local',
    [string]$PiUser = 'onyxpi',
    [string]$UpstreamInterface = 'Ethernet',
    [ValidateRange(0,3600)]
    [int]$StartupGraceSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Directory = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repository = (Resolve-Path (Join-Path $Directory '..\..')).Path
$WindowsDiagnostic = Join-Path $Directory 'Test-OnyxUsbIcsReadiness.ps1'
$PiDiagnostic = Join-Path $Repository 'pi\scripts\Test-OnyxUsbForwarding.py'
$DecisionEngine = Join-Path $Directory 'Evaluate-OnyxRecovery.py'

foreach ($Path in @($WindowsDiagnostic, $PiDiagnostic, $DecisionEngine)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required development component missing: $Path"
    }
}

$Branch = git -C $Repository branch --show-current
if ($LASTEXITCODE -ne 0 -or $Branch -ne 'feature/v0.6.0-reliability') {
    throw 'Run only from the isolated v0.6.0 development worktree.'
}

# Windows USB readiness. Any error is inconclusive, never repair authorization.
$WindowsError = $null
try {
    $WindowsResult = & $WindowsDiagnostic
    if ($null -eq $WindowsResult -or -not $WindowsResult.Classification) {
        throw 'Windows diagnostic returned no classification.'
    }
    $WindowsState = @{
        classification = [string]$WindowsResult.Classification
        route_via_usb = [bool]$WindowsResult.RouteViaUsb
        receiver_tcp_reachable = [bool]$WindowsResult.ReceiverTcpReachable
    }
}
catch {
    $WindowsError = $_.Exception.Message
    $WindowsState = @{ classification = 'WindowsProbeUnavailable' }
}

# Verify two distinct destinations from the expected *non-USB* interface.
$UpstreamTargets = @('1.1.1.1', '9.9.9.9')
$UpstreamResults = @()
foreach ($Target in $UpstreamTargets) {
    $Successful = $false
    $Interface = $null
    $SourceAddress = $null
    $ErrorText = $null
    try {
        $Probe = Test-NetConnection -ComputerName $Target -Port 443 `
            -InformationLevel Detailed -WarningAction SilentlyContinue
        $Interface = [string]$Probe.InterfaceAlias
        $SourceAddress = [string]$Probe.SourceAddress.IPAddress
        $Successful = (
            $Probe.TcpTestSucceeded -eq $true -and
            $Interface -eq $UpstreamInterface -and
            $SourceAddress -ne '192.168.137.1'
        )
    }
    catch {
        $ErrorText = $_.Exception.Message
    }
    $UpstreamResults += [PSCustomObject]@{
        target = "${Target}:443"
        tcp_on_expected_interface = $Successful
        interface = $Interface
        source_address = $SourceAddress
        error = $ErrorText
    }
}
$WindowsUpstreamOK = (
    @($UpstreamResults | Where-Object { -not $_.tcp_on_expected_interface }).Count -eq 0 -and
    $UpstreamResults.Count -eq $UpstreamTargets.Count
)

# Run the Pi diagnostic over SSH stdin. Does not install it on the Pi.
$PiError = $null
$PiState = @{
    classification = 'PiProbeUnavailable'
    gateway_reachable = $false
}
$PiFailedTargets = @()
$PiProbeDetails = $null
try {
    $Remote = "${PiUser}@${PiHostName}"
    $PiOutput = Get-Content -LiteralPath $PiDiagnostic -Raw -Encoding UTF8 |
        & ssh -T -o ConnectTimeout=8 $Remote python3 -
    $SshExit = $LASTEXITCODE
    if ($SshExit -ne 0) {
        throw "SSH or remote diagnostic failed with exit code $SshExit."
    }
    $PiProbeDetails = ($PiOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $PiProbeDetails -or -not $PiProbeDetails.classification) {
        throw 'Pi diagnostic did not return a classification.'
    }
    $PiState = @{
        classification = [string]$PiProbeDetails.classification
        gateway_reachable = ($PiProbeDetails.gateway_reachable -eq $true)
        dns_resolves = ($PiProbeDetails.dns_resolves -eq $true)
        https_works = ($PiProbeDetails.https_works -eq $true)
    }
    if ($null -ne $PiProbeDetails.external_tcp_failed_targets) {
        $PiFailedTargets = @($PiProbeDetails.external_tcp_failed_targets)
    }
}
catch {
    $PiError = $_.Exception.Message
    $PiFailedTargets = @()
}

# A report containing one fresh observation cannot trigger repeated-failure escalation.
$BootTime = $null
$StartupGraceElapsed = $null
try {
    $BootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $StartupGraceElapsed = ((Get-Date) - $BootTime).TotalSeconds -ge $StartupGraceSeconds
}
catch {
    # Unknown grace status results in an Investigate decision (fail closed).
}

$Observation = @{
    timestamp_utc = [DateTimeOffset]::UtcNow.ToString('o')
    windows = $WindowsState
    pi = $PiState
    windows_upstream_ok = $WindowsUpstreamOK
    external_tcp_failed_targets = @($PiFailedTargets)
}
$Report = @{
    startup_grace_elapsed = $StartupGraceElapsed
    observations = @($Observation)
}

# The decision engine accepts a file, so use a disposable JSON input file.
$TemporaryFile = [IO.Path]::GetTempFileName()
try {
    $Encoder = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        $TemporaryFile,
        ($Report | ConvertTo-Json -Depth 10),
        $Encoder
    )
    $DecisionOutput = & python $DecisionEngine --input $TemporaryFile
    if ($LASTEXITCODE -ne 0) {
        throw 'Decision engine exited unsuccessfully.'
    }
    $Decision = ($DecisionOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
    if ($Decision.repair_action -ne 'None') {
        throw 'Unexpected repair authorization in dry-run decision output.'
    }
}
finally {
    Remove-Item -LiteralPath $TemporaryFile -Force -ErrorAction SilentlyContinue
}

# Emit one structured record for inspection, without saving observation history.
[PSCustomObject]@{
    mode = 'ReadOnlySingleRun'
    observation = $Observation
    windows_upstream_targets = @($UpstreamResults)
    windows_error = $WindowsError
    pi_error = $PiError
    pi_details = $PiProbeDetails
    startup_grace_elapsed = $StartupGraceElapsed
    decision = $Decision
    repair_action = 'None'
}
