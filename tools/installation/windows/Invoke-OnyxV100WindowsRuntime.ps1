# ONYX CORE v1.0.0 M1-S6B: Windows configuration-driven runtime entry point.
# Preview is default; no network traffic, credentials or task changes in preview.
# Explicit execution is unapproved by this development checkpoint.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$InstalledRoot,
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][ValidateSet('Collector','Gateway')][string]$Component,
    [switch]$DryRun,
    [switch]$Run,
    [switch]$ApproveExecution
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
if ($ApproveExecution -and -not $Run) {
    throw 'Execution approval without -Run refused.'
}
if ($Run -and -not $ApproveExecution) {
    throw 'Execution requires explicit -Run and -ApproveExecution.'
}
if ($DryRun -and $Component -ne 'Collector') {
    throw 'DryRun is supported only for Collector.'
}

function Assert-PlainFile {
    param([string]$LiteralPath)
    if (-not [IO.Path]::IsPathRooted($LiteralPath) -or
        -not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw 'Expected absolute, existing regular file.'
    }
    $Current = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
    while ($null -ne $Current) {
        if ($Current.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Redirected runtime path refused.'
        }
        if ($Current -is [IO.FileInfo]) { $Current = $Current.Directory }
        else { $Current = $Current.Parent }
    }
}

if (-not [IO.Path]::IsPathRooted($InstalledRoot) -or
    -not (Test-Path -LiteralPath $InstalledRoot -PathType Container)) {
    throw 'Absolute, existing installed root required.'
}
$RootItem = Get-Item -LiteralPath $InstalledRoot -Force -ErrorAction Stop
if ($RootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Redirected installed root refused.'
}

$ConfigPath = (Get-Item -LiteralPath $ConfigPath -ErrorAction Stop).FullName
$PythonPath = (Get-Item -LiteralPath $PythonPath -ErrorAction Stop).FullName
$InstalledRoot = $RootItem.FullName

$Validator = Join-Path $InstalledRoot 'tools\installation\common\onyx_v100_config.py'
$Collector = Join-Path $InstalledRoot 'windows\collector\Send-OnyxTelemetry-v100.ps1'
$Gateway = Join-Path $InstalledRoot 'windows\gateway\OnyxGateway_v100.py'
$Dashboard = Join-Path $InstalledRoot 'windows\gateway\gateway-dashboard.html'

foreach ($File in @($ConfigPath, $PythonPath, $Validator, $Collector, $Gateway, $Dashboard)) {
    Assert-PlainFile $File
}

$Version = @(& $PythonPath --version 2>&1)
if ($LASTEXITCODE -ne 0 -or $Version.Count -ne 1 -or
    ([string]$Version[0]) -notmatch '^Python 3\.13\.[0-9]+$') {
    throw 'A working Python 3.13 executable is required.'
}

$Before = (Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256).Hash
$Lines = @(& $PythonPath -I -B $Validator --config $ConfigPath --platform windows 2>&1)
if ($LASTEXITCODE -ne 0 -or $Lines.Count -ne 1) {
    throw 'Versioned configuration validation refused.'
}
$Validation = $Lines[0] | ConvertFrom-Json -ErrorAction Stop
if ($Validation.operation -cne 'READ_ONLY_CONFIGURATION_VALIDATION' -or
    $Validation.valid -ne $true -or
    $Validation.platform -cne 'windows' -or
    $Validation.installation_accepted -ne $false -or
    $Validation.credential_contents_read -ne $false -or
    $Validation.service_or_task_changes -ne $false) {
    throw 'Unexpected configuration validation contract.'
}
$Cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 |
    ConvertFrom-Json -ErrorAction Stop
$After = (Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256).Hash
if ($Before -cne $After) {
    throw 'Configuration changed during validation.'
}

$CpuProperty = $Cfg.PSObject.Properties['cpu_temperature']
$CpuEnabled = ($null -ne $CpuProperty -and $CpuProperty.Value.enabled -eq $true)
$Preview = [ordered]@{
    schema_version = 1
    operation = 'WINDOWS_RUNTIME_PREVIEW'
    component = $Component
    config_sha256 = $Before
    runtime_source = $(if ($Component -eq 'Collector') { $Collector } else { $Gateway })
    receiver_host = $Cfg.receiver.host
    receiver_port = [int]$Cfg.receiver.port
    gateway_loopback = '127.0.0.1'
    gateway_port = [int]$Cfg.gateway.port
    collector_source = $Cfg.collector.source
    collector_interval_seconds = [int]$Cfg.collector.interval_seconds
    network_adapter = $Cfg.collector.network_adapter
    usb_adapter = $Cfg.usb.adapter_name
    cpu_temperature_enabled = [bool]$CpuEnabled
    dry_run = [bool]$DryRun
    activation_performed = $false
    credential_contents_read = $false
    task_or_service_changes = $false
    installation_accepted = $false
}
if (-not $Run) {
    $Preview | ConvertTo-Json -Depth 4 -Compress
    return
}

# This development command may be used in a later, separately approved stage.
# Never compete with an existing ONYX CORE task on a production host.
if (-not $DryRun) {
    $Protected = @(
        'ONYX CORE - Telemetry Collector',
        'ONYX CORE - Local Gateway',
        'ONYX CORE v0.9 - Telemetry Collector (Candidate)',
        'ONYX CORE v0.9 - Local Gateway (Candidate)'
    )
    foreach ($Name in $Protected) {
        if ($null -ne (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue)) {
            throw 'Existing ONYX CORE task detected; live execution requires an approved cutover workflow.'
        }
    }
    $Token = Join-Path $env:LOCALAPPDATA 'OnyxCore\collector-token.dpapi'
    Assert-PlainFile $Token
}

if ($Component -eq 'Collector') {
    $Argv = @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', $Collector,
        '-Receiver', [string]$Cfg.receiver.host,
        '-ReceiverPort', [string]$Cfg.receiver.port,
        '-Source', [string]$Cfg.collector.source,
        '-AdapterName', [string]$Cfg.collector.network_adapter,
        '-IntervalSeconds', [string]$Cfg.collector.interval_seconds,
        '-Count', $(if ($DryRun) { '1' } else { '0' })
    )
    if ($CpuEnabled) {
        $Argv += @('-EnableCpuTemperature',
                   '-CpuSensorEndpoint', [string]$Cfg.cpu_temperature.endpoint,
                   '-CpuSensorPath', [string]$Cfg.cpu_temperature.sensor_path)
    }
    if ($DryRun) { $Argv += '-DryRun' }
    else { $Argv += '-UseSavedToken' }
    & (Join-Path $PSHOME 'powershell.exe') @Argv
}
else {
    if ($DryRun) { throw 'Gateway cannot run in dry-run mode.' }
    & $PythonPath -I -B $Gateway `
        --dashboard $Dashboard `
        --receiver ([string]$Cfg.receiver.host) `
        --receiver-port ([string]$Cfg.receiver.port) `
        --port ([string]$Cfg.gateway.port) `
        --load-dpapi
}
if ($LASTEXITCODE -ne 0) {
    throw 'Versioned runtime exited unsuccessfully.'
}
