# Tests only the functions extracted from the collector AST. No real HTTP or credentials.
[CmdletBinding()]
param([string]$CollectorPath)

if ([string]::IsNullOrWhiteSpace($CollectorPath)) {
    $CollectorPath = Join-Path $PSScriptRoot 'Send-OnyxTelemetry.ps1'
}
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($CollectorPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw "PowerShell syntax errors: $($parseErrors.Count)" }
foreach ($name in @('Get-OnyxCpuTemperatureFromNode','Add-CpuTemperatureMetrics')) {
    $defs = @($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name}, $true))
    if ($defs.Count -ne 1) { throw "Missing or duplicate function: $name" }
    . ([scriptblock]::Create($defs[0].Extent.Text))
}
function Make-Tree([string]$Reading, [string]$Label = 'Core (Tctl/Tdie)') {
    [pscustomobject]@{Text='Sensor';Children=@(
        [pscustomobject]@{Text='SQUALL';Children=@(
            [pscustomobject]@{Text='AMD Ryzen 7 5800X';Children=@(
                [pscustomobject]@{Text='Temperatures';Children=@(
                    [pscustomobject]@{Text=$Label;Value=$Reading;Children=@()}
                )}
            )}
        )}
    )}
}
$script:MockTree=$null; $script:FailHttp=$false; $script:HttpCalls=0
function Invoke-RestMethod {
    param([string]$Uri,[int]$TimeoutSec,[string]$ErrorAction)
    if ($Uri -ne 'http://192.168.137.1:8085/data.json' -or $TimeoutSec -gt 2) { throw 'Unexpected request' }
    $script:HttpCalls++
    if ($script:FailHttp) { throw 'Simulated outage' }
    return $script:MockTree
}
function Assert-Test([bool]$Condition,[string]$Name) {
    if (-not $Condition) { throw "FAIL: $Name" }
    Write-Host "PASS: $Name"
}
$degree=[char]0x00B0
$script:MockTree=Make-Tree "67.1 ${degree}C"
$m=@{cpu_percent=15;gpu_percent=23;network_rx_bps=1234}
Add-CpuTemperatureMetrics -Metrics $m
Assert-Test ($m['cpu_temp_c'] -eq 67.1 -and $m['gpu_percent'] -eq 23) 'valid sensor preserves other metrics'
Assert-Test ($script:HttpCalls -eq 1) 'one sensor query'
$script:MockTree=Make-Tree "65,5 ${degree}C"
$m=@{cpu_percent=15}; Add-CpuTemperatureMetrics -Metrics $m
Assert-Test ($m['cpu_temp_c'] -eq 65.5) 'comma decimal accepted'
$script:MockTree=Make-Tree "58.0 ${degree}C" 'CCD1 (Tdie)'
$m=@{cpu_percent=15}; Add-CpuTemperatureMetrics -Metrics $m
Assert-Test (-not $m.ContainsKey('cpu_temp_c')) 'CCD not substituted'
$script:MockTree=Make-Tree 'not a temperature'
$m=@{cpu_percent=15}; Add-CpuTemperatureMetrics -Metrics $m
Assert-Test (-not $m.ContainsKey('cpu_temp_c')) 'invalid reading omitted'
$script:MockTree=Make-Tree "999 ${degree}C"
$m=@{cpu_percent=15}; Add-CpuTemperatureMetrics -Metrics $m
Assert-Test (-not $m.ContainsKey('cpu_temp_c')) 'implausible temperature omitted'
$script:FailHttp=$true
$m=@{cpu_percent=15;memory_used_percent=40}; Add-CpuTemperatureMetrics -Metrics $m
Assert-Test (-not $m.ContainsKey('cpu_temp_c') -and $m['memory_used_percent'] -eq 40) 'API failure preserves base metrics'
Write-Host 'PASS: 7 targeted checks'
