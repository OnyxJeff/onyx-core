# ONYX CORE v0.2.0 — foreground-only SQUALL collector prototype.
# No Scheduled Task, service, or secret persistence. Ctrl+C stops collection.
[CmdletBinding()]
param(
    [ValidateRange(5,3600)][int]$IntervalSeconds = 30,
    [ValidateRange(1,100000)][int]$Count = 5,
    [string]$Receiver = 'svr-onyxcore.local'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$endpoint = "http://${Receiver}:8765/api/v1/telemetry"
$sessionId = [guid]::NewGuid().ToString()
$credential = Read-Host 'Temporary ONYX CORE bearer token' -AsSecureString
$token = [System.Net.NetworkCredential]::new('', $credential).Password
if ($token.Length -lt 32) { throw 'Token must be at least 32 characters.' }
try {
    for ($sequence = 1; $sequence -le $Count; $sequence++) {
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
            # Never include token, payload, or Authorization header in logs.
            $status = 'transport'
            if ($null -ne $_.Exception.Response) {
                try { $status = [int]$_.Exception.Response.StatusCode } catch { }
            }
            Write-Warning ("Telemetry sequence {0} failed (status: {1}); next sample will use a new sequence." -f $sequence, $status)
        }
        if ($sequence -lt $Count) { Start-Sleep -Seconds $IntervalSeconds }
    }
}
finally {
    Remove-Variable token,credential -ErrorAction SilentlyContinue
}
