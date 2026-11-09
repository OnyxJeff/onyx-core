# ONYX CORE v0.7.0 - guarded release-only USB/ICS evidence collector.
# Never run directly: the Python one-shot runtime holds the exclusive state lock.
[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\monitoring\monitoring.release.example.json'),
    [switch]$LiveReadOnly,
    [switch]$AuthorizedReleaseRunner
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# No implicit probes, state writes or SSH. Every real cycle requires opt-in.
if (-not $LiveReadOnly) {
    throw 'Refusing to run diagnostic probes without explicit -LiveReadOnly.'
}

$Directory = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repository = (Resolve-Path (Join-Path $Directory '..\..')).Path
$WindowsDiagnostic = Join-Path $Directory 'Test-OnyxUsbIcsReadiness.ps1'
$DecisionEngine = Join-Path $Directory 'Evaluate-OnyxRecovery.py'
$Validator = Join-Path $Repository 'windows\monitoring\OnyxReleasePolicy.py'
$ApprovedConfigPath = Join-Path $Repository 'windows\monitoring\monitoring.release.example.json'
$MaxHistoryAgeSeconds = 300
$MaxObservations = 12
$MaxHistoryBytes = 262144

# Release diagnostics can only be called by the explicitly authorized Python
# one-shot runtime. This string is NOT an authentication secret; Git, config,
# source and store checks are the actual defensive boundaries.
if (-not $AuthorizedReleaseRunner -or
    $env:ONYX_CORE_V070_RELEASE_LIVE -ne 'approved-one-shot') {
    throw 'Release collector requires the supervised one-shot runtime.'
}

# All source verification occurs BEFORE Windows/Pi network access.
$Branch = & git -C $Repository branch --show-current
if ($LASTEXITCODE -ne 0 -or $Branch -ne 'main' -or
    -not [string]::Equals($Repository, 'D:\github_repos\onyx-core',
       [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Release collector requires the reviewed main installation.'
}
foreach ($Path in @($WindowsDiagnostic, $DecisionEngine, $Validator, $ApprovedConfigPath)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required release component missing: $Path"
    }
}
$ResolvedConfigPath = (Resolve-Path -LiteralPath $ConfigPath -ErrorAction Stop).Path
if (-not [string]::Equals($ResolvedConfigPath,
        (Resolve-Path -LiteralPath $ApprovedConfigPath).Path,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Only the reviewed release configuration is supported.'
}
$Dirty = @(& git -C $Repository status --porcelain=v1 --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $Dirty.Count -gt 0) {
    throw 'Tracked release files are modified.'
}
$Untracked = @(& git -C $Repository status --porcelain=v1 -uall -- 'windows/monitoring/' 'windows/networking/')
if ($LASTEXITCODE -ne 0 -or $Untracked.Count -gt 0) {
    throw 'Unexpected release monitoring/networking source.'
}
$BootstrapPython = 'C:\Python313\python.exe'
if (-not (Test-Path -LiteralPath $BootstrapPython -PathType Leaf)) {
    throw 'Approved release Python runtime missing.'
}
$null = & $BootstrapPython $Validator --check $ResolvedConfigPath
if ($LASTEXITCODE -ne 0) {
    throw 'Release monitoring configuration validation failed.'
}
$Config = Get-Content -LiteralPath $ResolvedConfigPath -Raw -Encoding UTF8 |
    ConvertFrom-Json -ErrorAction Stop

$AdapterName = [string]$Config.windows.adapter_name
$GatewayIP = [string]$Config.windows.gateway_ip
$ReceiverIP = [string]$Config.windows.receiver_ip
$ReceiverPort = [int]$Config.windows.receiver_port
$ReceiverTimeoutMs = [int]$Config.timeouts.receiver_tcp_ms
$UpstreamInterface = [string]$Config.windows.upstream_interface
$PiHostName = [string]$Config.pi.hostname
$PiUser = [string]$Config.pi.user
$StartupGraceSeconds = [int]$Config.startup_grace_seconds
$SshTimeoutSeconds = [int]$Config.timeouts.ssh_seconds
$UpstreamTcpTimeoutMs = [int]$Config.timeouts.upstream_tcp_ms
$MonitorKeyPath = [Environment]::ExpandEnvironmentVariables([string]$Config.pi.monitor_key_path)
$HistoryDirectory = [Environment]::ExpandEnvironmentVariables([string]$Config.state_dir)
$HistoryPath = Join-Path $HistoryDirectory 'recovery-observations.json'
$PythonExecutable = [string]$Config.runtime.python_executable
$SshPath = [string]$Config.runtime.ssh_executable

foreach ($Path in @($MonitorKeyPath, $PythonExecutable, $SshPath)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required runtime file missing: $Path"
    }
}

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
        $Result.error = "History unusable: $($_.Exception.Message)"
    }
    return $Result
}

function Write-OnyxHistory {
    param([string]$Path, [object[]]$Observations)
    $Parent = Split-Path -Parent $Path
    if (-not $Parent) { throw 'History path must have a parent directory.' }
    $null = New-Item -ItemType Directory -Path $Parent -Force -ErrorAction Stop
    $TemporaryPath = Join-Path $Parent ('.onyx-v070-' + [guid]::NewGuid().ToString('N') + '.tmp')
    # .NET Framework / Windows PowerShell 5.1 may reject a null backup path.
    # Keep the swap atomic by using a valid backup in the SAME directory.
    $BackupPath = Join-Path $Parent ('.onyx-v070-' + [guid]::NewGuid().ToString('N') + '.bak')
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
$Mutex = New-Object System.Threading.Mutex($false, 'Local\OnyxCoreV070ReleaseRecoveryEvidence')
$LockTaken = $false
try {
    try { $LockTaken = $Mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $LockTaken = $true }
    if (-not $LockTaken) { throw 'Another v0.7.0 evidence collection is in progress.' }

    $WindowsError = $null
    try {
        $WindowsResult = & $WindowsDiagnostic `
            -AdapterName $AdapterName `
            -GatewayIP $GatewayIP `
            -ReceiverIP $ReceiverIP `
            -ReceiverPort $ReceiverPort `
            -TimeoutMs $ReceiverTimeoutMs
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
            $HistoryError = 'History clock regression; existing evidence preserved.'
        }
    }
    $Observations = @($Observations + @($Observation))
    if ($Observations.Count -gt $MaxObservations) {
        $Observations = @($Observations | Select-Object -Last $MaxObservations)
    }
    if ($null -eq $HistoryError) {
        try {
            if (Test-Path -LiteralPath $HistoryPath -PathType Leaf) {
                $HistoryItem = Get-Item -LiteralPath $HistoryPath -Force -ErrorAction Stop
                if (($HistoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw 'Redirected release history refused.'
                }
            }
            Write-OnyxHistory -Path $HistoryPath -Observations $Observations
        }
        catch { $HistoryError = "Cannot persist history: $($_.Exception.Message)" }
    }
    # Preserve corrupt/clock-regressed bytes for manual review; no reset.


    $Report = @{
        startup_grace_elapsed = $StartupGraceElapsed
        observations = @($Observations)
    }
    $TemporaryFile = [IO.Path]::GetTempFileName()
    try {
        $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($TemporaryFile, ($Report | ConvertTo-Json -Depth 12), $Utf8NoBom)
        $DecisionOutput = & $PythonExecutable $DecisionEngine --input $TemporaryFile
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
