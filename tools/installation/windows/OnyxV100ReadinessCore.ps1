# ONYX CORE v1.0.0 M1-S2: pure, offline-testable classification helpers.
# No filesystem, credential, network, process or service operations.
Set-StrictMode -Version Latest

function Test-OnyxV100PythonVersion {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$VersionText)

    $value = ([string]$VersionText).Trim()
    $match = [regex]::Match($value, '^Python\s+(\d+)\.(\d+)\.(\d+)\s*$')
    if (-not $match.Success) {
        return [pscustomobject][ordered]@{
            version = $null
            supported = $false
            reason = 'Version output is not a plain Python version.'
        }
    }

    $major = [int]$match.Groups[1].Value
    $minor = [int]$match.Groups[2].Value
    $patch = [int]$match.Groups[3].Value
    $supported = ($major -eq 3 -and $minor -eq 13)
    $reason = if ($supported) { 'Supported Python 3.13 series.' } else {
        'Only Python 3.13.x is accepted by the initial v1.0.0 baseline.'
    }
    return [pscustomobject][ordered]@{
        version = ('{0}.{1}.{2}' -f $major, $minor, $patch)
        supported = [bool]$supported
        reason = $reason
    }
}

function Test-OnyxV100UsbHint {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$Name,
          [AllowEmptyString()][string]$Description)

    $description = [string]$Description
    $nameText = [string]$Name
    # Hints only: a matching name is not proof of the correct USB device.
    if ($description -match '(?i)(RNDIS|Remote NDIS|Raspberry Pi|Linux USB Gadget|USB[ -]?Ethernet)') {
        return $true
    }
    if ($nameText -match '(?i)(RNDIS|Raspberry Pi)') {
        return $true
    }
    return $false
}

function Get-OnyxV100ReadinessDecision {
    [CmdletBinding()]
    param(
        [bool]$Windows11,
        [bool]$PowerShell51,
        [bool]$PythonSupported,
        [bool]$TaskSchedulerAvailable,
        [int]$UsbCandidates,
        [bool]$DpapiTokenPresent,
        [bool]$ExistingOnyxTasks
    )

    $blockers = New-Object 'System.Collections.Generic.List[string]'
    $actions = New-Object 'System.Collections.Generic.List[string]'

    if (-not $Windows11) { $blockers.Add('Supported Windows 11 workstation was not verified.') }
    if (-not $PowerShell51) { $blockers.Add('Windows PowerShell 5.1 is required.') }
    if (-not $PythonSupported) { $blockers.Add('A verified Python 3.13.x interpreter is required.') }
    if (-not $TaskSchedulerAvailable) { $blockers.Add('Windows Scheduled Tasks are unavailable for inspection.') }
    if ($UsbCandidates -eq 0) { $actions.Add('Identify the USB RNDIS Ethernet interface; no candidate was detected.') }
    if (-not $DpapiTokenPresent) { $actions.Add('Enroll a DPAPI token under the intended task user after Pi provisioning.') }
    if ($ExistingOnyxTasks) { $actions.Add('Existing ONYX CORE tasks detected: use the upgrade workflow, not clean-host registration.') }

    $actions.Add('Validate Windows ICS and Raspberry Pi USB readiness in a separately authorized stage.')
    $actions.Add('Validate configuration and receiver authentication before activation.')

    $state = if ($blockers.Count -gt 0) { 'BLOCKED' } else { 'REQUIRES_CONFIGURATION' }
    return [pscustomobject][ordered]@{
        state = $state
        supported_base_prerequisites = ($blockers.Count -eq 0)
        blockers = @($blockers.ToArray())
        operator_actions = @($actions.ToArray())
        installation_accepted = $false
    }
}
