# ONYX CORE v0.6.0 - read-only, manually invoked recovery evidence collector.
# Isolated development state only. NEVER modifies ICS, services, or production telemetry.
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]*$')]
    [string]$PiHostName = 'svr-onyxcore.local',
    [ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]*$')]
    [string]$PiUser = 'onyxpi',
    [string]$UpstreamInterface = 'Ethernet',
    [ValidateRange(0,3600)]
    [int]$StartupGraceSeconds = 180,
    [ValidateRange(10,90)]
    [int]$SshTimeoutSeconds = 45,
    [ValidateRange(500,10000)]
    [int]$UpstreamTcpTimeoutMs = 3000,
    [string]$MonitorKeyPath = (Join-Path $env:USERPROFILE '.ssh\onyxcore_monitor_ed25519'),
    [string]$HistoryPath = (Join-Path $env:LOCALAPPDATA 'OnyxCore-v060-Development\recovery-observations.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Directory = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repository = (Resolve-Path (Join-Path $Directory '..\..')).Path
$WindowsDiagnostic = Join-Path $Directory 'Test-OnyxUsbIcsReadiness.ps1'
$DecisionEngine = Join-Path $Directory 'Evaluate-OnyxRecovery.py'
$MaxHistoryAgeSeconds = 300
$MaxObservations = 12
$MaxHistoryBytes = 262144

# Verify both the branch and the dedicated worktree name before any I/O/probes.
$Branch = (& git -C $Repository branch --show-current)
if ($LASTEXITCODE -ne 0 -or $Branch -ne 'feature/v0.6.0-reliability' -or
    (Split-Path -Leaf $Repository) -ne 'onyx-core-v060') {
    throw 'Refusing to run outside the isolated v0.6.0 development worktree.'
}
foreach ($Path in @($WindowsDiagnostic, $DecisionEngine)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required development component missing: $Path"
    }
}
if (-not (Test-Path -LiteralPath $MonitorKeyPath -PathType Leaf)) {
    throw "Dedicated SSH private key not found: $MonitorKeyPath"
}
$SshExecutable = Get-Command 'ssh.exe' -CommandType Application -ErrorAction Stop
$SshPath = $SshExecutable.Source

function Invoke-OnyxBoundedSsh {
    param(
        [string]$Executable,
        [string]$KeyPath,
        [string]$Remote,
        [int]$TimeoutSeconds
    )

    # ProcessStartInfo on Windows PowerShell 5.1 accepts a single argument string.
    # Windows paths cannot contain double quotes. Quote only the private-key path.
    $Arguments = @(
        '-T', '-n', '-i', ('"' + $KeyPath + '"'),
        '-o', 'IdentitiesOnly=yes',
        '-o', 'BatchMode=yes',
        '-o', 'PreferredAuthentications=publickey',
        '-o', 'PasswordAuthentication=no',
        '-o', 'KbdInteractiveAuthentication=no',
        '-o', 'NumberOfPasswordPrompts=0',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=8',
        '-o', 'ConnectionAttempts=1',
        '-o', 'ServerAliveInterval=5',
        '-o', 'ServerAliveCountMax=1',
        $Remote, 'onyxcore-monitor'
    ) -join ' '
    $Start = New-Object System.Diagnostics.ProcessStartInfo
    $Start.FileName = $Executable
    $Start.Arguments = $Arguments
    $Start.UseShellExecute = $false
    $Start.CreateNoWindow = $true
    $Start.RedirectStandardOutput = $true
    $Start.RedirectStandardError = $true

    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $Start
    try {
        if (-not $Process.Start()) {
            throw 'Could not launch SSH.'
        }
        # Drain both streams while waiting so redirected pipe buffers cannot deadlock.
        $OutTask = $Process.StandardOutput.ReadToEndAsync()
        $ErrTask = $Process.StandardError.ReadToEndAsync()
        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $Process.Kill() } catch { }
            $null = $Process.WaitForExit(2000)
            throw "SSH/remote diagnostic exceeded the ${TimeoutSeconds}s wall-clock limit."
        }
        $StandardOutput = $OutTask.GetAwaiter().GetResult()
        $StandardError = $ErrTask.GetAwaiter().GetResult()
        if ($Process.ExitCode -ne 0) {
            $BriefError = $StandardError.Trim()
            if ($BriefError.Length -gt 500) { $BriefError = $BriefError.Substring(0,500) }
            throw "SSH/remote diagnostic exit $($Process.ExitCode): $BriefError"
        }
        if ($StandardOutput.Length -gt 65536) {
            throw 'Remote diagnostic returned too much output.'
        }
        return $StandardOutput
    }
    finally {
        $Process.Dispose()
    }
}

function Test-OnyxUpstreamTcp {
    param([string]$Target, [string]$ExpectedInterface, [int]$TimeoutMs)
    $Successful = $false
    $Interface = $null
    $SourceAddress = $null
    $ErrorText = $null
    $Client = New-Object System.Net.Sockets.TcpClient -ArgumentList ([System.Net.Sockets.AddressFamily]::InterNetwork)
    $AsyncResult = $null
    try {
        $AsyncResult = $Client.BeginConnect($Target, 443, $null, $null)
        if (-not $AsyncResult.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            throw "TCP connect exceeded ${TimeoutMs}ms."
        }
        $Client.EndConnect($AsyncResult)
        $SourceAddress = ([System.Net.IPEndPoint]$Client.Client.LocalEndPoint).Address.ToString()
        $AddressInfo = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $SourceAddress -ErrorAction Stop |
            Select-Object -First 1
        if ($null -eq $AddressInfo) { throw 'Cannot map TCP source IP to a Windows interface.' }
        $Interface = [string]$AddressInfo.InterfaceAlias
        $Successful = ($Interface -eq $ExpectedInterface -and
            $SourceAddress -ne '192.168.137.1')
    }
    catch {
        $ErrorText = $_.Exception.Message
    }
    finally {
        if ($null -ne $AsyncResult) { $AsyncResult.AsyncWaitHandle.Close() }
        $Client.Close()
    }
    return [PSCustomObject]@{
        target = "${Target}:443"
        tcp_on_expected_interface = $Successful
        interface = $Interface
        source_address = $SourceAddress
        error = $ErrorText
    }
}

function Read-OnyxHistory {
    param([string]$Path, [DateTimeOffset]$Now)
    $Result = @{ observations = @(); error = $null }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $Result }
    try {
        $Item = Get-Item -LiteralPath $Path -ErrorAction Stop
        if ($Item.Length -gt $MaxHistoryBytes) { throw 'Stored history exceeds size limit.' }
        $Stored = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $Stored -or
            $null -eq $Stored.PSObject.Properties['schema_version'] -or
            $Stored.schema_version -ne 1 -or
            $null -eq $Stored.PSObject.Properties['observations'] -or
            $Stored.observations -isnot [array] -or
            $Stored.observations.Count -gt $MaxObservations) {
            throw 'Stored history has an invalid schema or count.'
        }
        $Valid = @()
        $PreviousTime = [DateTimeOffset]::MinValue
        foreach ($Entry in $Stored.observations) {
            if ($null -eq $Entry -or
                $null -eq $Entry.PSObject.Properties['timestamp_utc'] -or
                $null -eq $Entry.PSObject.Properties['windows'] -or
                $null -eq $Entry.PSObject.Properties['pi'] -or
                $null -eq $Entry.PSObject.Properties['windows_upstream_ok'] -or
                $null -eq $Entry.PSObject.Properties['external_tcp_failed_targets'] -or
                $null -eq $Entry.windows -or $null -eq $Entry.pi -or
                $null -eq $Entry.windows.PSObject.Properties['classification'] -or
                $null -eq $Entry.pi.PSObject.Properties['classification'] -or
                $Entry.external_tcp_failed_targets -isnot [array]) {
                throw 'Stored history contains an invalid observation.'
            }
            $Stamp = [DateTimeOffset]::Parse(
                [string]$Entry.timestamp_utc,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::RoundtripKind
            ).ToUniversalTime()
            if ($Stamp -le $PreviousTime -or $Stamp -gt $Now.AddSeconds(5)) {
                throw 'Stored history is unordered or future-dated.'
            }
            $PreviousTime = $Stamp
            if ($Stamp -ge $Now.AddSeconds(-$MaxHistoryAgeSeconds)) {
                $Valid += $Entry
            }
        }
        $Result.observations = @($Valid)
    }
    catch {
        # Discard all untrusted continuity; never escalate based on corrupt history.
        $Result.observations = @()
        $Result.error = "History reset: $($_.Exception.Message)"
    }
    return $Result
}

function Write-OnyxHistory {
    param([string]$Path, [object[]]$Observations)
    $Parent = Split-Path -Parent $Path
    if (-not $Parent) { throw 'History path must have a parent directory.' }
    $null = New-Item -ItemType Directory -Path $Parent -Force -ErrorAction Stop
    $TemporaryPath = Join-Path $Parent ('.onyx-v060-' + [guid]::NewGuid().ToString('N') + '.tmp')
    # .NET Framework / Windows PowerShell 5.1 may reject a null backup path.
    # Keep the swap atomic by using a valid backup in the SAME directory.
    $BackupPath = Join-Path $Parent ('.onyx-v060-' + [guid]::NewGuid().ToString('N') + '.bak')
    try {
        $Payload = @{
            schema_version = 1
            updated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            observations = @($Observations)
        }
        $Json = $Payload | ConvertTo-Json -Depth 12
        $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($TemporaryPath, $Json, $Utf8NoBom)
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            [IO.File]::Replace($TemporaryPath, $Path, $BackupPath)
        }
        else {
            [IO.File]::Move($TemporaryPath, $Path)
        }
    }
    finally {
        # Remove temporary/backup artifacts after either success or failure.
        foreach ($CleanupPath in @($TemporaryPath, $BackupPath)) {
            if (Test-Path -LiteralPath $CleanupPath -PathType Leaf) {
                Remove-Item -LiteralPath $CleanupPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# Prevent concurrent invocations from interleaving reads/writes or counting duplicates.
$Mutex = New-Object System.Threading.Mutex($false, 'Local\OnyxCoreV060RecoveryEvidence')
$LockTaken = $false
try {
    try { $LockTaken = $Mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $LockTaken = $true }
    if (-not $LockTaken) { throw 'Another v0.6.0 evidence collection is in progress.' }

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

    $UpstreamResults = @(
        foreach ($Target in @('1.1.1.1', '9.9.9.9')) {
            Test-OnyxUpstreamTcp -Target $Target -ExpectedInterface $UpstreamInterface -TimeoutMs $UpstreamTcpTimeoutMs
        }
    )
    $WindowsUpstreamOK = (@($UpstreamResults | Where-Object {
        -not $_.tcp_on_expected_interface
    }).Count -eq 0 -and $UpstreamResults.Count -eq 2)

    $PiError = $null
    $PiState = @{ classification = 'PiProbeUnavailable'; gateway_reachable = $false }
    $PiFailedTargets = @()
    $PiProbeDetails = $null
    try {
        $PiOutput = Invoke-OnyxBoundedSsh -Executable $SshPath -KeyPath $MonitorKeyPath `
            -Remote "${PiUser}@${PiHostName}" -TimeoutSeconds $SshTimeoutSeconds
        $PiProbeDetails = $PiOutput | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $PiProbeDetails -or -not $PiProbeDetails.classification -or
            $PiProbeDetails.repair_action -ne 'None') {
            throw 'Pi diagnostic did not return a valid read-only classification.'
        }
        $PiState = @{
            classification = [string]$PiProbeDetails.classification
            gateway_reachable = ($PiProbeDetails.gateway_reachable -eq $true)
            dns_resolves = ($PiProbeDetails.dns_resolves -eq $true)
            https_works = ($PiProbeDetails.https_works -eq $true)
        }
        if ($null -ne $PiProbeDetails.external_tcp_failed_targets) {
            $PiFailedTargets = @($PiProbeDetails.external_tcp_failed_targets)
            if (@($PiFailedTargets | Where-Object {
                $_ -notin @('1.1.1.1:443', '9.9.9.9:443')
            }).Count -gt 0) {
                throw 'Pi returned an unexpected external TCP target.'
            }
        }
    }
    catch {
        $PiError = $_.Exception.Message
        $PiState = @{ classification = 'PiProbeUnavailable'; gateway_reachable = $false }
        $PiFailedTargets = @()
    }

    $StartupGraceElapsed = $null
    try {
        $BootTime = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
        $StartupGraceElapsed = ((Get-Date) - $BootTime).TotalSeconds -ge $StartupGraceSeconds
    }
    catch { }

    $Observation = @{
        timestamp_utc = [DateTimeOffset]::UtcNow.ToString('o')
        windows = $WindowsState
        pi = $PiState
        windows_upstream_ok = $WindowsUpstreamOK
        external_tcp_failed_targets = @($PiFailedTargets)
    }
    $Now = [DateTimeOffset]::UtcNow
    $Loaded = Read-OnyxHistory -Path $HistoryPath -Now $Now
    $HistoryError = $Loaded.error
    $Observations = @($Loaded.observations)
    if ($Observations.Count -gt 0) {
        $Last = [DateTimeOffset]::Parse([string]$Observations[-1].timestamp_utc).ToUniversalTime()
        if ($Last -ge [DateTimeOffset]::Parse([string]$Observation.timestamp_utc)) {
            $Observations = @()
            $HistoryError = 'History reset: system clock is not monotonic.'
        }
    }
    $Observations = @($Observations + @($Observation))
    if ($Observations.Count -gt $MaxObservations) {
        $Observations = @($Observations | Select-Object -Last $MaxObservations)
    }
    try { Write-OnyxHistory -Path $HistoryPath -Observations $Observations }
    catch { $HistoryError = "Cannot persist history: $($_.Exception.Message)" }

    $Report = @{
        startup_grace_elapsed = $StartupGraceElapsed
        observations = @($Observations)
    }
    $TemporaryFile = [IO.Path]::GetTempFileName()
    try {
        $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($TemporaryFile, ($Report | ConvertTo-Json -Depth 12), $Utf8NoBom)
        $DecisionOutput = & python $DecisionEngine --input $TemporaryFile
        if ($LASTEXITCODE -ne 0) { throw 'Decision engine exited unsuccessfully.' }
        $Decision = ($DecisionOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $Decision -or $Decision.repair_action -ne 'None') {
            throw 'Decision engine did not return a valid read-only result.'
        }
    }
    catch {
        $Decision = [PSCustomObject]@{
            decision = 'Investigate'
            reason = "Decision engine unavailable: $($_.Exception.Message)"
            consecutive_suspected = 0
            repair_action = 'None'
        }
    }
    finally {
        Remove-Item -LiteralPath $TemporaryFile -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $HistoryError) {
        $Decision = [PSCustomObject]@{
            decision = 'Investigate'
            reason = 'History integrity or persistence unavailable; escalation suppressed'
            consecutive_suspected = 0
            repair_action = 'None'
        }
    }

    [PSCustomObject]@{
        mode = 'ReadOnlyPersistentHistory'
        observation = $Observation
        observation_count = $Observations.Count
        history_path = $HistoryPath
        history_error = $HistoryError
        windows_upstream_targets = @($UpstreamResults)
        windows_error = $WindowsError
        pi_error = $PiError
        pi_details = $PiProbeDetails
        startup_grace_elapsed = $StartupGraceElapsed
        decision = $Decision
        repair_action = 'None'
    }
}
finally {
    if ($LockTaken) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}
