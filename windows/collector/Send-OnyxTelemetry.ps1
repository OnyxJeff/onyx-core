# ONYX CORE v0.2.0 — Windows 5.1 foreground collector; no task installed.
# Count=0 loops until Ctrl+C. Run as the DPAPI token's Windows user.
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
try {
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { throw 'ONYX CORE collector is already running in this Windows session.' }
    if ($UseSavedToken) {
        $file = Join-Path $env:LOCALAPPDATA 'OnyxCore\collector-token.dpapi'
        if (-not (Test-Path -LiteralPath $file)) { throw 'Missing protected token. Run Save-OnyxToken.ps1 as this user.' }
        $credential = Get-Content -LiteralPath $file -Raw | ConvertTo-SecureString
    } else {
        $credential = Read-Host 'ONYX CORE bearer token' -AsSecureString
    }
    $token = [System.Net.NetworkCredential]::new('', $credential).Password
    if ($token.Length -lt 32) { throw 'Token must be at least 32 characters.' }
    $sequence = 0L
    while ($Count -eq 0 -or $sequence -lt $Count) {
        $sequence++
        try {
            $os = Get-CimInstance Win32_OperatingSystem
            $cpus = @(Get-CimInstance Win32_Processor)
            $load = ($cpus | Measure-Object -Property LoadPercentage -Average).Average
            if ($null -eq $load) { throw 'CPU LoadPercentage unavailable' }
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
            Write-Host ("{0} accepted sequence={1} CPU={2}% RAM={3}%" -f (Get-Date -Format 'HH:mm:ss'), $response.sequence, $metrics.cpu_percent, $metrics.memory_used_percent)
        } catch {
            $status = 'transport-or-collection'
            if ($null -ne $_.Exception.Response) {
                try { $status = [int]$_.Exception.Response.StatusCode } catch { }
            }
            Write-Warning ("Telemetry sequence {0} failed ({1}); continuing." -f $sequence, $status)
        }
        if ($Count -eq 0 -or $sequence -lt $Count) { Start-Sleep -Seconds $IntervalSeconds }
    }
} finally {
    $token = $null
    Remove-Variable credential,token -ErrorAction SilentlyContinue
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
