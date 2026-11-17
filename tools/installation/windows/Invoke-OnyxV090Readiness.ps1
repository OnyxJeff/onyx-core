# Windows PowerShell 5.1 read-only environment prerequisite report.
# No network probes, task changes, secret reads, service control or file writes.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Python = 'C:\Python313\python.exe'
$SSH = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
$RelevantTaskNames = @('ONYX CORE - Telemetry Collector',
                       'ONYX CORE - Local Gateway', 'LibreHardwareMonitor')
$Tasks = @()
foreach ($Name in $RelevantTaskNames) {
    $Task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    $Tasks += [PSCustomObject]@{
        name = $Name
        exists = ($null -ne $Task)
        state = $(if ($null -ne $Task) { [string]$Task.State } else { 'Absent' })
    }
}
$PythonVersion = $null
if (Test-Path -LiteralPath $Python -PathType Leaf) {
    $PythonVersion = (& $Python --version 2>&1 | Out-String).Trim()
}
$Report = [ordered]@{
    schema_version = 1
    host = $env:COMPUTERNAME
    powershell_version = [string]$PSVersionTable.PSVersion
    powershell_5_1 = ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1)
    python_executable_present = (Test-Path -LiteralPath $Python -PathType Leaf)
    python_version = $PythonVersion
    openssh_present = (Test-Path -LiteralPath $SSH -PathType Leaf)
    protected_v080_directory_present = (Test-Path -LiteralPath 'C:\Program Files\OnyxCore\v0.8.0' -PathType Container)
    candidate_v090_directory_present = (Test-Path -LiteralPath 'C:\Program Files\OnyxCore\v0.9.0' -PathType Container)
    scheduled_task_status = $Tasks
    observation_only = $true
}
[PSCustomObject]$Report | ConvertTo-Json -Depth 5
