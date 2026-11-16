# Protected *runtime* wrapper. It does not install tasks or alter production.
# Deployment must pin this exact source into the administrator-owned approval.
[CmdletBinding()]
param([switch]$ApproveProtectedAlerts)
$ErrorActionPreference = 'Stop'
$Install = 'C:\Program Files\OnyxCore\v0.8.0'
$Python = 'C:\Python313\python.exe'
$Worker = Join-Path $Install 'windows\monitoring\v080\OnyxV080ProtectedLogonRuntime.py'
$ExpectedSelf = Join-Path $Install 'windows\monitoring\v080\operations\Start-OnyxV080ProtectedDiscord.ps1'
$Base = Join-Path $env:LOCALAPPDATA 'OnyxCore-v080-Development\NotificationConfig'
$SealedPath = Join-Path $Base 'destination.dpapi'
$ProviderPath = Join-Path $Base 'provider.txt'
if (-not $ApproveProtectedAlerts) { throw 'Explicit -ApproveProtectedAlerts required.' }
if (-not [string]::Equals($MyInvocation.MyCommand.Path, $ExpectedSelf,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Protected Discord wrapper must execute from fixed installation.'
}
foreach ($Item in @($Python, $Worker, $SealedPath, $ProviderPath)) {
    if (-not (Test-Path -LiteralPath $Item -PathType Leaf)) {
        throw 'Protected Discord prerequisite missing.'
    }
}
if (([IO.File]::ReadAllText($ProviderPath, [Text.Encoding]::ASCII)).Trim() -ne 'discord') {
    throw 'Configured provider must be Discord.'
}
if ($env:ONYXCORE_V080_ALERT_WEBHOOK_URL -or $env:ONYXCORE_V080_ALERT_TOKEN -or
    ($env:ONYXCORE_V080_STORAGE_PROFILE -and $env:ONYXCORE_V080_STORAGE_PROFILE -ne 'release')) {
    throw 'Unexpected inherited notification or storage environment.'
}
$Secure = ([IO.File]::ReadAllText($SealedPath, [Text.Encoding]::ASCII)).Trim() | ConvertTo-SecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
try {
    $env:ONYXCORE_V080_ALERT_WEBHOOK_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
}
$PreviousProfile = [Environment]::GetEnvironmentVariable('ONYXCORE_V080_STORAGE_PROFILE', 'Process')
try {
    $env:ONYXCORE_V080_STORAGE_PROFILE = 'release'
    & $Python -I -B $Worker --run-approved-alerts
    if ($LASTEXITCODE -ne 0) { throw 'Protected Discord worker exited abnormally.' }
}
finally {
    Remove-Item Env:ONYXCORE_V080_ALERT_WEBHOOK_URL -ErrorAction SilentlyContinue
    [Environment]::SetEnvironmentVariable('ONYXCORE_V080_STORAGE_PROFILE', $PreviousProfile, 'Process')
}
