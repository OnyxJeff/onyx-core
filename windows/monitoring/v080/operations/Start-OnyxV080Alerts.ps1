# Development ONLY. Requires the current user's DPAPI-sealed webhook.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$Repo = 'D:\github_repos\onyx-core-v080'
$Branch = 'feature/v0.8.0-continuous-monitoring'
$Python = 'C:\Python313\python.exe'
$Program = Join-Path $Repo 'windows\monitoring\v080\OnyxIncidentNotifications.py'
$Base = Join-Path $env:LOCALAPPDATA 'OnyxCore-v080-Development\NotificationConfig'
$Target = Join-Path $Base 'destination.dpapi'
$Metadata = Join-Path $Base 'provider.txt'
if ((& git -C $Repo branch --show-current) -ne $Branch -or $LASTEXITCODE -ne 0) {
    throw 'Refusing alert startup outside approved development branch.'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Program -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Target -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Metadata -PathType Leaf)) {
    throw 'Alert startup prerequisites missing.'
}
$Provider = [IO.File]::ReadAllText($Metadata, [Text.Encoding]::ASCII).Trim()
if ($Provider -notin @('ntfy','discord','json')) { throw 'Invalid notification provider.' }
$Sec = [IO.File]::ReadAllText($Target, [Text.Encoding]::ASCII).Trim() | ConvertTo-SecureString
$Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Sec)
try {
    $env:ONYXCORE_V080_ALERT_WEBHOOK_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr)
}
try {
    # M5 validates URL and provider before sending anything. First run
    # baselines existing incident events. Starts only under explicit task action.
    & $Python -B $Program --watch --provider $Provider --poll-seconds 15 --monitor-stale-seconds 420
    if ($LASTEXITCODE -ne 0) { throw 'Notification process exited abnormally.' }
}
finally {
    Remove-Item Env:ONYXCORE_V080_ALERT_WEBHOOK_URL -ErrorAction SilentlyContinue
}
