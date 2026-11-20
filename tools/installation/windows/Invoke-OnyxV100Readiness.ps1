# ONYX CORE v1.0.0 M1-S2: observational Windows installation readiness.
# No writes, network probes, credentials reads, task changes, repairs or installs.
# Python candidates are launched ONLY with -I -B --version (bounded to 4 seconds).
[CmdletBinding()]
param(
    [string]$PythonPath = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'OnyxV100ReadinessCore.ps1')

function Get-OnyxV100PythonCandidates {
    param([string]$Requested)

    $paths = New-Object 'System.Collections.Generic.List[string]'
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        if (-not [IO.Path]::IsPathRooted($Requested)) {
            throw 'Explicit -PythonPath must be absolute.'
        }
        $paths.Add($Requested)
    } else {
        # PATH, normal system installation directories and per-user Python installs.
        $apps = @(Get-Command -Name python.exe -All -CommandType Application -ErrorAction SilentlyContinue)
        foreach ($app in $apps) {
            if ($null -ne $app -and $app.Source) { $paths.Add([string]$app.Source) }
        }
        $systemRoot = [IO.Path]::GetPathRoot($env:SystemRoot)
        if ($systemRoot -and (Test-Path -LiteralPath $systemRoot -PathType Container)) {
            foreach ($folder in @(Get-ChildItem -LiteralPath $systemRoot -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue)) {
                $paths.Add((Join-Path $folder.FullName 'python.exe'))
            }
        }
        $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        if (Test-Path -LiteralPath $localPython -PathType Container) {
            foreach ($folder in @(Get-ChildItem -LiteralPath $localPython -Directory -ErrorAction SilentlyContinue)) {
                $paths.Add((Join-Path $folder.FullName 'python.exe'))
            }
        }
    }

    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $result = New-Object 'System.Collections.Generic.List[string]'
    foreach ($path in $paths) {
        if ([string]::IsNullOrWhiteSpace($path) -or -not [IO.Path]::IsPathRooted($path)) { continue }
        $full = [IO.Path]::GetFullPath($path)
        if (-not $seen.Add($full)) { continue }
        if ($result.Count -ge 16) { break }
        $result.Add($full)
    }
    return @($result.ToArray())
}

function Get-OnyxV100PythonProbe {
    param([string]$Executable)

    $row = [ordered]@{
        path = $Executable
        version = $null
        supported = $false
        status = 'NOT_FOUND'
    }
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return [pscustomobject]$row
    }
    # Never execute Microsoft Store/App Execution Alias stubs during discovery.
    if ($Executable -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/]') {
        $row.status = 'WINDOWS_APP_ALIAS_NOT_EXECUTED'
        return [pscustomobject]$row
    }

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $proc.StartInfo.FileName = $Executable
    $proc.StartInfo.Arguments = '-I -B --version'
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.CreateNoWindow = $true
    $proc.StartInfo.RedirectStandardOutput = $true
    $proc.StartInfo.RedirectStandardError = $true
    try {
        if (-not $proc.Start()) {
            $row.status = 'START_FAILED'
            return [pscustomobject]$row
        }
        if (-not $proc.WaitForExit(4000)) {
            try { $proc.Kill() } catch { }
            $row.status = 'TIMEOUT'
            return [pscustomobject]$row
        }
        $stdout = $proc.StandardOutput.ReadToEnd().Trim()
        $stderr = $proc.StandardError.ReadToEnd().Trim()
        if ($proc.ExitCode -ne 0) {
            $row.status = 'NONZERO_EXIT'
            return [pscustomobject]$row
        }
        $candidate = if ($stdout) { $stdout } else { $stderr }
        $parsed = Test-OnyxV100PythonVersion -VersionText $candidate
        $row.version = $parsed.version
        $row.supported = $parsed.supported
        $row.status = if ($parsed.supported) { 'SUPPORTED' } else { 'UNSUPPORTED_VERSION' }
    } catch {
        # Avoid reporting exception text (which can reveal local paths/details).
        $row.status = 'PROBE_FAILED'
    } finally {
        $proc.Dispose()
    }
    return [pscustomobject]$row
}

function Invoke-OnyxV100Readiness {
    param([string]$RequestedPythonPath)

    $ps51 = ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1)
    $osVersion = [ordered]@{
        caption = $null
        build = $null
        workstation = $false
        windows_11 = $false
        inspection_available = $false
    }
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        $build = [int]$os.BuildNumber
        $osVersion.caption = [string]$os.Caption
        $osVersion.build = $build
        $osVersion.workstation = ([int]$os.ProductType -eq 1)
        $osVersion.windows_11 = ($osVersion.workstation -and $build -ge 22000)
        $osVersion.inspection_available = $true
    } catch { }

    $python = @()
    foreach ($candidate in @(Get-OnyxV100PythonCandidates -Requested $RequestedPythonPath)) {
        $python += Get-OnyxV100PythonProbe -Executable $candidate
    }
    $supportedPython = @($python | Where-Object { $_.supported }).Count -gt 0

    $usb = @()
    if ($null -ne (Get-Command -Name Get-NetAdapter -ErrorAction SilentlyContinue)) {
        try {
            $adapters = @(Get-NetAdapter -IncludeHidden -ErrorAction Stop)
            foreach ($adapter in $adapters) {
                if (Test-OnyxV100UsbHint -Name ([string]$adapter.Name) -Description ([string]$adapter.InterfaceDescription)) {
                    $usb += [pscustomobject][ordered]@{
                        name = [string]$adapter.Name
                        description = [string]$adapter.InterfaceDescription
                        status = [string]$adapter.Status
                        interface_index = [int]$adapter.ifIndex
                    }
                }
            }
        } catch { }
    }

    $taskAvailable = $null -ne (Get-Command -Name Get-ScheduledTask -ErrorAction SilentlyContinue)
    $tasks = @()
    $taskInspectionSucceeded = $false
    if ($taskAvailable) {
        try {
            $tasks = @(Get-ScheduledTask -TaskName 'ONYX CORE*' -ErrorAction Stop |
                Select-Object TaskName, State)
            $taskInspectionSucceeded = $true
        } catch {
            # Get-ScheduledTask may return a not-found error on a clean host.
            try {
                $tasks = @(Get-ScheduledTask -ErrorAction Stop |
                    Where-Object { $_.TaskName -like 'ONYX CORE*' } |
                    Select-Object TaskName, State)
                $taskInspectionSucceeded = $true
            } catch { }
        }
    }

    $appRoot = Join-Path $env:ProgramFiles 'OnyxCore'
    $versionDirs = @()
    if (Test-Path -LiteralPath $appRoot -PathType Container) {
        $versionDirs = @(Get-ChildItem -LiteralPath $appRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^v\d+\.\d+\.\d+$' } |
            Select-Object -ExpandProperty Name)
    }
    $tokenFile = Join-Path $env:LOCALAPPDATA 'OnyxCore\collector-token.dpapi'
    $tokenPresent = Test-Path -LiteralPath $tokenFile -PathType Leaf
    $decision = Get-OnyxV100ReadinessDecision `
        -Windows11 $osVersion.windows_11 `
        -PowerShell51 $ps51 `
        -PythonSupported $supportedPython `
        -TaskSchedulerAvailable ($taskAvailable -and $taskInspectionSucceeded) `
        -UsbCandidates $usb.Count `
        -DpapiTokenPresent $tokenPresent `
        -ExistingOnyxTasks ($tasks.Count -gt 0)

    return [pscustomobject][ordered]@{
        schema_version = 1
        operation = 'READ_ONLY_WINDOWS_INSTALL_PREFLIGHT'
        observation_only = $true
        has_network_probes = $false
        credential_contents_read = $false
        service_or_task_changes = $false
        os = $osVersion
        powershell_5_1 = $ps51
        python = [ordered]@{
            required_series = '3.13.x'
            supported_detected = $supportedPython
            candidates = @($python)
        }
        usb = [ordered]@{
            candidate_count = $usb.Count
            candidate_hints_only = $true
            candidates = @($usb)
            ics_verified = $false
        }
        existing_install = [ordered]@{
            onyx_tasks = @($tasks)
            task_inspection_succeeded = $taskInspectionSucceeded
            version_directories = @($versionDirs)
            dpapi_token_file_present = [bool]$tokenPresent
            protected_v080_directory_present = (Test-Path -LiteralPath (Join-Path $appRoot 'v0.8.0') -PathType Container)
        }
        readiness = $decision
    }
}

Invoke-OnyxV100Readiness -RequestedPythonPath $PythonPath | ConvertTo-Json -Depth 9
