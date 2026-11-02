# ONYX CORE v0.2.0 — Windows PowerShell 5.1 telemetry collector.
# Count=0 continuously sends samples until stopped. No secret or payload logging.
[CmdletBinding()]
param(
    [ValidateRange(5,3600)][int]$IntervalSeconds = 30,
    [ValidateRange(0,100000)][int]$Count = 5,
    [string]$Receiver = 'svr-onyxcore.local',
    [switch]$UseSavedToken
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$endpoint = "http://${Receiver}:8765/api/v1/telemetry"
$sessionId = [guid]::NewGuid().ToString()
$mutex = New-Object System.Threading.Mutex($false, 'Local\OnyxCoreCollector')
$locked = $false
$token = $null
$credential = $null
$failures = 0
$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore'
$logFile = Join-Path $logDir 'collector.log'
$launcherPid = $null
$launcherStarted = $null

function Write-CollectorEvent {
    param([string]$Level, [string]$Message)
    $line = '{0} [{1}] {2}' -f [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'), $Level, $Message
    Write-Host $line
    # Keep one previous 1 MiB log; never print credentials, payloads or raw exceptions.
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
    } catch {
        return $false
    }
}

try {
    # When spawned through wscript, remember the exact parent process instance.
    # A stopped Scheduled Task can kill wscript while leaving PowerShell alive.
    $self = Get-CimInstance Win32_Process -Filter "ProcessId = $PID"
    if ($null -ne $self) {
        $parentInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($self.ParentProcessId)"
        if ($null -ne $parentInfo -and $parentInfo.Name -eq 'wscript.exe' -and
            $parentInfo.CommandLine -like '*Launch-OnyxTelemetry.vbs*') {
            $launcherPid = [int]$parentInfo.ProcessId
            $launcherStarted = (Get-Process -Id $launcherPid -ErrorAction Stop).StartTime
        }
    }
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
    Write-CollectorEvent INFO "Collector started; interval=${IntervalSeconds}s; count=$Count."
    $sequence = 0L
    while ($Count -eq 0 -or $sequence -lt $Count) {
        if (-not (Test-LauncherAlive)) {
            Write-CollectorEvent INFO 'Launcher exited; collector stopping.'
            break
        }
        $sequence++
        $outcome = $null
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
            $sample = @{
                schema_version = 1
                source = 'SQUALL'
                session_id = $sessionId
                timestamp_utc = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
                sequence = [long]$sequence
                metrics = $metrics
            } | ConvertTo-Json -Depth 4 -Compress
            $response = Invoke-RestMethod -Uri $endpoint -Method Post -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($sample)) -TimeoutSec 5
            if ($response.accepted -ne $true -or [long]$response.sequence -ne $sequence) {
                throw 'Unexpected acknowledgment.'
            }
            Write-CollectorEvent INFO "Accepted sequence=$sequence."
        } catch {
            $failures++
            $status = 'transport-or-collection'
            if ($null -ne $_.Exception.Response) {
                try { $status = [string][int]$_.Exception.Response.StatusCode } catch { }
            }
            Write-CollectorEvent WARN "Failed sequence=$sequence; status=$status."
            if ($status -eq '401') {
                Write-CollectorEvent ERROR 'Receiver rejected credentials; stopping to avoid repeated unauthorized requests.'
                break
            }
        }
        if ($Count -eq 0 -or $sequence -lt $Count) {
            # Check launcher liveness in short intervals to release the mutex promptly.
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
    # Do not log raw errors: some web/cmdlet errors can expose sensitive context.
    if ($locked) {
        try { Write-CollectorEvent ERROR 'Collector could not initialize or complete.' } catch { }
    }
    exit 2
} finally {
    $token = $null
    Remove-Variable credential,token -ErrorAction SilentlyContinue
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
