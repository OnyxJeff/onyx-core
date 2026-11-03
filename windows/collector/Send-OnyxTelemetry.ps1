# ONYX CORE v0.5.0 - development collector; not the production scheduled-task target.
# -DryRun never reads credentials, sends network requests, or writes collector logs.
[CmdletBinding()]
param(
    [ValidateRange(5,3600)][int]$IntervalSeconds = 30,
    [ValidateRange(0,100000)][int]$Count = 5,
    [string]$Receiver = 'svr-onyxcore.local',
    [string]$AdapterName = 'Ethernet',
    [switch]$UseSavedToken,
    [switch]$DryRun
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($DryRun -and $Count -eq 0) { throw 'DryRun requires a finite -Count.' }
$endpoint = "http://${Receiver}:8765/api/v1/telemetry"
$sessionId = [guid]::NewGuid().ToString()
$mutex = $null
$locked = $false
$token = $null
$credential = $null
$failures = 0
$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore'
$logFile = Join-Path $logDir 'collector.log'
$launcherPid = $null
$launcherStarted = $null
$previousNetwork = $null
$previousNetworkTime = $null

function Write-CollectorEvent {
    param([string]$Level, [string]$Message)
    $line = '{0} [{1}] {2}' -f [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'), $Level, $Message
    Write-Host $line
    if ($DryRun) { return }
    if (Test-Path -LiteralPath $logFile) {
        if ((Get-Item -LiteralPath $logFile).Length -ge 1MB) {
            Move-Item -LiteralPath $logFile -Destination ($logFile + '.1') -Force
        }
    }
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

function Test-LauncherAlive {
    if ($null -eq $launcherPid) { return $true }
    try {
        $parent = Get-Process -Id $launcherPid -ErrorAction Stop
        return $parent.StartTime -eq $launcherStarted
    } catch { return $false }
}

function Add-NvidiaMetrics {
    param([hashtable]$Metrics)
    try {
        $smi = (Get-Command nvidia-smi.exe -ErrorAction Stop).Source
        $lines = @(& $smi --query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null)
        if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) { return }
        $parts = @($lines[0] -split ',\s*')
        if ($parts.Count -ne 4) { return }
        $values = @()
        foreach ($part in $parts) {
            $n = 0.0
            if (-not [double]::TryParse($part.Trim(), [System.Globalization.NumberStyles]::Float,
                [System.Globalization.CultureInfo]::InvariantCulture, [ref]$n)) { return }
            $values += $n
        }
        if ($values[0] -lt 0 -or $values[0] -gt 100 -or
            $values[1] -lt -20 -or $values[1] -gt 150 -or
            $values[2] -lt 0 -or $values[3] -le 0 -or
            $values[3] -gt 1048576 -or $values[2] -gt $values[3]) { return }
        $Metrics['gpu_percent'] = $values[0]
        $Metrics['gpu_temp_c'] = $values[1]
        $Metrics['gpu_vram_used_mib'] = $values[2]
        $Metrics['gpu_vram_total_mib'] = $values[3]
    } catch {
        # Optional metrics must never prevent base telemetry collection.
    }
}

function Add-NetworkMetrics {
    param([hashtable]$Metrics)
    try {
        $adapter = Get-NetAdapter -Name $AdapterName -ErrorAction Stop
        if ($adapter.Status -ne 'Up') { return }
        $stats = Get-NetAdapterStatistics -Name $AdapterName -ErrorAction Stop
        $now = [datetime]::UtcNow
        if ($null -ne $previousNetwork) {
            $seconds = ($now - $previousNetworkTime).TotalSeconds
            $rx = [double]$stats.ReceivedBytes - [double]$previousNetwork.ReceivedBytes
            $tx = [double]$stats.SentBytes - [double]$previousNetwork.SentBytes
            if ($seconds -gt 0 -and $rx -ge 0 -and $tx -ge 0) {
                $rxRate = [math]::Round($rx * 8 / $seconds)
                $txRate = [math]::Round($tx * 8 / $seconds)
                if ($rxRate -le 1e12 -and $txRate -le 1e12) {
                    $Metrics['network_rx_bps'] = $rxRate
                    $Metrics['network_tx_bps'] = $txRate
                }
            }
        }
        $script:previousNetwork = $stats
        $script:previousNetworkTime = $now
    } catch {
        # Adapter absent, reset, or disconnected. Retry on next cycle.
        $script:previousNetwork = $null
        $script:previousNetworkTime = $null
    }
}

try {
    if (-not $DryRun) {
        # The existing VBS parent check prevents orphan collection after task shutdown.
        $self = Get-CimInstance Win32_Process -Filter "ProcessId = $PID"
        if ($null -ne $self) {
            $parentInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($self.ParentProcessId)"
            if ($null -ne $parentInfo -and $parentInfo.Name -eq 'wscript.exe' -and
                $parentInfo.CommandLine -like '*Launch-OnyxTelemetry.vbs*') {
                $launcherPid = [int]$parentInfo.ProcessId
                $launcherStarted = (Get-Process -Id $launcherPid -ErrorAction Stop).StartTime
            }
        }
        $mutex = New-Object System.Threading.Mutex($false, 'Local\OnyxCoreCollector')
        $locked = $mutex.WaitOne(0)
        if (-not $locked) { throw 'Collector already running in this Windows session.' }
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        if ($UseSavedToken) {
            $file = Join-Path $logDir 'collector-token.dpapi'
            if (-not (Test-Path -LiteralPath $file)) { throw 'Protected token file is missing.' }
            $credential = Get-Content -LiteralPath $file -Raw | ConvertTo-SecureString
        } else {
            if (-not [Environment]::UserInteractive) { throw 'Unattended collection requires -UseSavedToken.' }
            $credential = Read-Host 'ONYX CORE bearer token' -AsSecureString
        }
        $token = [System.Net.NetworkCredential]::new('', $credential).Password
        if ($token.Length -lt 32) { throw 'Token must be at least 32 characters.' }
    }

    Write-CollectorEvent INFO "Collector started; interval=${IntervalSeconds}s; count=$Count; dryrun=$DryRun."
    $sequence = 0L
    while ($Count -eq 0 -or $sequence -lt $Count) {
        if (-not (Test-LauncherAlive)) {
            Write-CollectorEvent INFO 'Launcher exited; collector stopping.'
            break
        }
        $sequence++
        try {
            $os = Get-CimInstance Win32_OperatingSystem
            $cpus = @(Get-CimInstance Win32_Processor)
            $load = ($cpus | Measure-Object -Property LoadPercentage -Average).Average
            if ($null -eq $load -or $os.TotalVisibleMemorySize -le 0) { throw 'Invalid counter data.' }
            $metrics = @{
                cpu_percent = [math]::Round([double]$load, 2)
                memory_used_percent = [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 2)
                uptime_seconds = [long]([datetime]::Now - $os.LastBootUpTime).TotalSeconds
            }
            Add-NvidiaMetrics -Metrics $metrics
            Add-NetworkMetrics -Metrics $metrics
            $payload = @{
                schema_version = 1
                source = 'SQUALL'
                session_id = $sessionId
                timestamp_utc = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
                sequence = [long]$sequence
                metrics = $metrics
            }
            if ($DryRun) {
                # Prints metric data only; no credentials, no HTTP request.
                $payload | ConvertTo-Json -Depth 4 -Compress | Write-Output
            } else {
                $sample = $payload | ConvertTo-Json -Depth 4 -Compress
                $response = Invoke-RestMethod -Uri $endpoint -Method Post -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($sample)) -TimeoutSec 5
                if ($response.accepted -ne $true -or [long]$response.sequence -ne $sequence) {
                    throw 'Unexpected acknowledgment.'
                }
                Write-CollectorEvent INFO "Accepted sequence=$sequence."
            }
        } catch {
            $failures++
            if ($DryRun) {
                Write-CollectorEvent WARN "Collection failed sequence=$sequence; no telemetry sent."
            } else {
                $status = 'transport-or-collection'
                if ($null -ne $_.Exception.Response) {
                    try { $status = [string][int]$_.Exception.Response.StatusCode } catch { }
                }
                Write-CollectorEvent WARN "Failed sequence=$sequence; status=$status."
                if ($status -eq '401') {
                    Write-CollectorEvent ERROR 'Receiver rejected credentials; stopping.'
                    break
                }
            }
        }
        if ($Count -eq 0 -or $sequence -lt $Count) {
            $remaining = $IntervalSeconds
            while ($remaining -gt 0) {
                if (-not (Test-LauncherAlive)) { break }
                $slice = [math]::Min(2, $remaining)
                Start-Sleep -Seconds $slice
                $remaining -= $slice
            }
        }
    }
    Write-CollectorEvent INFO "Collector stopped; attempts=$sequence; failures=$failures."
    if ($failures -gt 0) { exit 1 }
    exit 0
} catch {
    if ($locked -or $DryRun) {
        try { Write-CollectorEvent ERROR 'Collector could not initialize or complete.' } catch { }
    }
    exit 2
} finally {
    $token = $null
    Remove-Variable credential,token -ErrorAction SilentlyContinue
    if ($locked) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
