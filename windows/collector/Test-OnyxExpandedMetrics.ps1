# ONYX CORE v0.5.0 - isolated Phase 3B metric probe
# Does not modify the running collector, scheduled task, token, or Pi.
[CmdletBinding()]
param(
    [ValidateRange(2,30)][int]$SampleSeconds = 3,
    [string]$AdapterName = 'Ethernet'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NvidiaMetrics {
    $smi = (Get-Command nvidia-smi.exe -ErrorAction Stop).Source
    $lines = @(& $smi --query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) { throw 'NVIDIA query failed or returned multiple GPUs.' }
    $parts = @($lines[0] -split ',\s*')
    if ($parts.Count -ne 4) { throw 'Unexpected NVIDIA CSV format.' }
    $values = @()
    foreach ($part in $parts) {
        $number = 0.0
        if (-not [double]::TryParse($part.Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$number)) {
            throw 'NVIDIA returned an unavailable or nonnumeric metric.'
        }
        $values += $number
    }
    if ($values[0] -lt 0 -or $values[0] -gt 100 -or $values[1] -lt -20 -or $values[1] -gt 130 -or
        $values[2] -lt 0 -or $values[3] -le 0 -or $values[2] -gt $values[3]) {
        throw 'NVIDIA returned out-of-range metrics.'
    }
    return [ordered]@{
        gpu_percent = $values[0]
        gpu_temp_c = $values[1]
        gpu_vram_used_mib = $values[2]
        gpu_vram_total_mib = $values[3]
    }
}

function Get-NetworkMetrics {
    param([string]$Name, [int]$Seconds)
    $adapter = Get-NetAdapter -Name $Name -ErrorAction Stop
    if ($adapter.Status -ne 'Up') { throw "Network adapter '$Name' is not up." }
    $before = Get-NetAdapterStatistics -Name $Name -ErrorAction Stop
    $started = [System.Diagnostics.Stopwatch]::StartNew()
    Start-Sleep -Seconds $Seconds
    $after = Get-NetAdapterStatistics -Name $Name -ErrorAction Stop
    $started.Stop()
    $elapsed = $started.Elapsed.TotalSeconds
    $rx = [double]$after.ReceivedBytes - [double]$before.ReceivedBytes
    $tx = [double]$after.SentBytes - [double]$before.SentBytes
    if ($rx -lt 0 -or $tx -lt 0 -or $elapsed -le 0) { throw 'Invalid interface counter delta.' }
    return [ordered]@{
        adapter = $Name
        measured_seconds = [math]::Round($elapsed, 2)
        network_rx_bps = [math]::Round($rx * 8 / $elapsed)
        network_tx_bps = [math]::Round($tx * 8 / $elapsed)
    }
}

Write-Host '=== ONYX CORE v0.5.0 / ISOLATED METRIC PROBE ==='
Write-Host 'No telemetry is transmitted. No configuration is changed.'
try {
    $gpu = Get-NvidiaMetrics
    Write-Host 'GPU: OK'
    [pscustomobject]$gpu | Format-List | Out-Host
} catch {
    Write-Warning ('GPU probe unavailable: ' + $_.Exception.Message)
}
try {
    $network = Get-NetworkMetrics -Name $AdapterName -Seconds $SampleSeconds
    Write-Host 'NETWORK: OK'
    [pscustomobject]$network | Format-List | Out-Host
} catch {
    Write-Warning ('Network probe unavailable: ' + $_.Exception.Message)
}
